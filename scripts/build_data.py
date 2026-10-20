#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_data.py — 把麦当劳 MCP 的真实返回转换为前端可渲染的数据文件

流程:
    query-nearby-stores (定位门店)
        -> query-meals         (菜单: 分类 / 编码 / 价格 / 标签)
        -> query-store-coupons (门店可用券, 含适用商品编码)
        -> list-nutrition-foods(营养数据, 按名称匹配餐品)
    再聚合「不错过提醒」:
        query-my-coupons / available-coupons / query-my-account
        query-lottery-info / query-my-prizes / campaign-calendar

输出: assets/data.js  (window.MCD_REAL_DATA = {...})

用法:
    export MCD_MCP_TOKEN='你的Token'
    python3 scripts/build_data.py --city 深圳市 --keyword 科技园
    python3 scripts/build_data.py --store-code 1420762
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

MCP_URL = "https://mcp.mcd.cn"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# =============================================================================
# MCP 调用
# =============================================================================
def mcp_call(tool: str, arguments: dict, token: str) -> str:
    """调用 MCP tools/call，返回 content[0].text"""
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[MCP] HTTP {e.code}：{e.read().decode('utf-8','ignore')[:300]}")
    if "error" in body:
        raise SystemExit(f"[MCP] 工具 {tool} 调用失败：{body['error']}")
    content = body.get("result", {}).get("content", [])
    return content[0].get("text", "") if content else ""


def extract_json(raw: str):
    """MCP 返回是「说明文字 + 原始 JSON」，这里把最外层完整的 JSON 抠出来"""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        pos = raw.find(opener)
        while pos != -1:
            depth, in_str, esc, end = 0, False, False, None
            for i in range(pos, len(raw)):
                c = raw[i]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                    continue
                if c == '"':
                    in_str = True
                elif c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end is not None:
                try:
                    parsed = json.loads(raw[pos:end + 1])
                except Exception:
                    parsed = None
                if isinstance(parsed, dict) and ("data" in parsed or "success" in parsed):
                    return parsed
                if isinstance(parsed, list):
                    return parsed
            pos = raw.find(opener, pos + 1)
    return None


def to_float(v, default=0.0):
    try:
        s = str(v).replace("¥", "").replace("元", "").strip()
        return float(s) if s else default
    except Exception:
        return default


def to_int(v, default=0):
    try:
        return int(to_float(v, default))
    except Exception:
        return default


# =============================================================================
# 营养数据解析（紧凑文本格式）
# =============================================================================
def parse_nutrition(raw: str) -> dict:
    """data 字段是紧凑文本:
       [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
         猪柳麦满分,null,1288,308,16,16,24,781,213
    """
    result = {}
    body = extract_json(raw)
    text = ""
    if isinstance(body, dict):
        text = body.get("data") or ""
    if not text and isinstance(body, str):
        text = body
    if not text:
        text = raw

    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("[") or s.startswith("{"):
            continue
        parts = [p.strip() for p in s.split(",")]
        if len(parts) < 8:
            continue
        name = parts[0]
        if not name or name.lower() == "productname":
            continue
        nums = []
        for p in parts[2:9]:
            m = re.search(r"-?\d+(?:\.\d+)?", p)
            nums.append(float(m.group()) if m else 0.0)
        while len(nums) < 7:
            nums.append(0.0)
        result[name] = {
            "energyKj": nums[0], "energyKcal": nums[1], "protein": nums[2],
            "fat": nums[3], "carb": nums[4], "sodium": nums[5], "calcium": nums[6],
        }
    return result


def bigrams(s: str) -> set:
    s = re.sub(r"[\s()（）\-—·]+", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set()


# 规格词：菜单名带「麦咖啡™美式」，营养库叫「冰美式中杯」，去掉规格后核心名一致
SPEC_RE = re.compile(r"(中杯|大杯|小杯|中份|大份|小份|热|冰|块|™|麦咖啡)")
# 人工核对过的别名（菜单名 → 营养库条目名），一律按估算打 ≈ 标记
NUTRI_ALIAS = {
    "灰焰圆筒": "圆筒冰淇淋",
    "经典麦旋风": "奥利奥麦旋风",
    "蓝莓爆爆珠麦旋风": "草莓麦旋风",
    "阳光橙麦炫酷": "麦旋酷阳光橙",
}


def core_name(s: str) -> str:
    s = SPEC_RE.sub("", s or "")
    s = re.sub(r"[\s()（）\[\]【】]+", "", s)   # 统一括号，避免「纯牛奶(盒装)」被「热牛奶中杯」抢走
    return s


def match_nutrition(name: str, nutri: dict):
    """按餐品名匹配营养数据，三档精度：
       1) 归一化后精确/包含            —— 可信，直接采用
       2) 去掉规格词后核心名一致/包含   —— 估算（杯型可能不同），打 ≈
       3) 2-gram Jaccard ≥ 0.45        —— 估算，打 ≈
       都不中则返回 None，前端显示「热量待核」，绝不编造。
    """
    if not nutri:
        return None
    if name in nutri:
        return dict(nutri[name], kcalEstimated=False)

    flat = re.sub(r"[\s]+", "", name or "")
    for k, v in nutri.items():
        if re.sub(r"[\s]+", "", k) == flat:
            return dict(v, kcalEstimated=False)
    for k, v in nutri.items():
        if flat and (flat in k or k in flat):
            return dict(v, kcalEstimated=False)

    # 档 2：规格归一后的核心名（麦咖啡™美式 → 冰美式中杯）
    cn = core_name(name)
    if cn:
        # 先取核心名完全一致，再退到包含，保证「纯牛奶（盒装）」优先于「热牛奶中杯」
        for k, v in nutri.items():
            if core_name(k) == cn:
                return dict(v, kcalEstimated=True)
        for k, v in nutri.items():
            ck = core_name(k)
            if ck and (cn in ck or ck in cn):
                return dict(v, kcalEstimated=True)

    # 档 2.5：人工核对过的别名（词序/口味变体）
    alias = NUTRI_ALIAS.get((name or "").strip())
    if alias and alias in nutri:
        return dict(nutri[alias], kcalEstimated=True)

    # 档 3：新品/促销品（如「龙焰芝士棒鸡腿堡三件套」）按字粒度相似度匹配
    nb = bigrams(name)
    if not nb:
        return None
    best, best_score = None, 0.0
    for k, v in nutri.items():
        kb = bigrams(k)
        if not kb:
            continue
        inter = len(nb & kb)
        score = inter / len(nb | kb)
        if score > best_score:
            best, best_score = v, score
    if best and best_score >= 0.45:
        return dict(best, kcalEstimated=True)
    return None


# =============================================================================
# 场景化分类引擎
# 规则完全基于 MCP 真实返回的 name / cat / tags / price / kcal / protein
# =============================================================================
SCENES = [
    {"id": "breakfast", "name": "健康早餐", "icon": "🌅",
     "desc": "轻盈开局 · 目标 ≤ 450 kcal", "kcalMax": 450, "priceMax": 25},
    {"id": "office", "name": "办公下午茶", "icon": "☕",
     "desc": "三点钟的回血时刻 · 目标 ≤ 30 元", "kcalMax": 400, "priceMax": 30},
    {"id": "kids", "name": "儿童套餐", "icon": "🧒",
     "desc": "小朋友的快乐 · 目标 ≤ 450 kcal", "kcalMax": 450, "priceMax": 40},
    {"id": "fitness", "name": "健身运动餐", "icon": "💪",
     "desc": "高蛋白控卡 · 蛋白 ≥ 15g", "kcalMax": 550, "proteinMin": 15},
    {"id": "beauty", "name": "悦己养颜餐", "icon": "🌸",
     "desc": "犒赏自己的小甜头 · 目标 ≤ 400 kcal", "kcalMax": 400, "priceMax": 35},
]

BREAKFAST_RE = re.compile(r"早餐|麦满分|粥|豆浆|早安|晨")
OFFICE_RE = re.compile(r"咖啡|美式|拿铁|奶铁|卡布|茶|可乐|雪碧|薯条|派|麦旋风|新地|冰淇淋|圆筒|阳光柠檬")
KIDS_RE = re.compile(r"开心乐园|儿童|牛奶|苹果片|玉米|果汁|迷你|FUN")
FITNESS_RE = re.compile(r"板烧|吉士|鸡胸|沙拉|牛肉|鳕鱼|麦满分|蛋")
BEAUTY_RE = re.compile(r"冰淇淋|新地|麦旋风|派|圆筒|甜品|蛋糕|草莓|朱古力|香芋|菠萝|布丁|红豆|奶茶")


def classify_scenes(it: dict) -> list:
    """给单个餐品打场景标签（可多标签）"""
    hay = f"{it.get('name','')} {it.get('cat','')} {' '.join(it.get('tags') or [])}"
    price = it.get("price", 0)
    kcal = it.get("kcal", 0)
    protein = it.get("protein", 0)
    scenes = []

    if BREAKFAST_RE.search(hay) and price <= 25:
        scenes.append("breakfast")

    if OFFICE_RE.search(hay) and price <= 30 and kcal <= 450:
        scenes.append("office")

    if KIDS_RE.search(hay):
        scenes.append("kids")

    # 健身：中等热量 + 较高蛋白（有营养数据时才判定，避免瞎猜）
    if kcal > 0 and kcal <= 550 and protein >= 15 and (FITNESS_RE.search(hay) or protein / max(kcal, 1) >= 0.05):
        scenes.append("fitness")
    elif re.search(r"500大卡", it.get("cat", "")):
        scenes.append("fitness")

    if BEAUTY_RE.search(hay) and kcal <= 400:
        scenes.append("beauty")

    return scenes


def fallback_pick(scene_id: str, menu: list) -> list:
    """场景在当前时段无命中时的兜底推荐（例如非早餐时段没有早餐品）"""
    with_kcal = [m for m in menu if m.get("kcal", 0) > 0]
    if scene_id == "breakfast":
        # 兜底优先取主食/蛋/粥类，而不是单纯挑最低热量（否则会推出「红茶+冰咖啡」）
        staple = [m for m in with_kcal if re.search(r"堡|卷|满分|粥|蛋|早餐", m["name"])]
        pool = sorted(staple, key=lambda m: m["kcal"])[:8] or \
               sorted(with_kcal, key=lambda m: m["kcal"])[:8] or menu[:8]
    elif scene_id == "office":
        pool = [m for m in menu if re.search(r"咖啡|饮|茶|派", m["cat"] + m["name"])][:8] or menu[:8]
    elif scene_id == "kids":
        pool = [m for m in menu if re.search(r"牛奶|果汁|玉米|迷你|苹果|乐园", m["name"])][:8] or menu[:8]
    elif scene_id == "fitness":
        pool = sorted([m for m in with_kcal if m.get("protein", 0) >= 15],
                      key=lambda m: -m.get("protein", 0))[:8] or menu[:8]
    elif scene_id == "beauty":
        pool = [m for m in menu if re.search(r"甜品|冰淇淋|派|新地|旋风|圆筒", m["cat"] + m["name"])][:8] or menu[:8]
    else:
        pool = menu[:8]
    for m in pool:
        if scene_id not in m.get("scenes", []):
            m.setdefault("scenes", []).append(scene_id)
            m["sceneFallback"] = True
    return pool


def build_scene_bundles(menu: list) -> list:
    """为每个场景生成 3 套推荐组合（预算/热量约束下枚举）"""
    out = []
    for sc in SCENES:
        pool = [m for m in menu if sc["id"] in (m.get("scenes") or [])]
        is_fallback = False
        if not pool:
            pool = fallback_pick(sc["id"], menu)
            is_fallback = bool(pool)
        if not pool:
            out.append({**sc, "count": 0, "bundles": [], "fallback": False})
            continue

        kcal_max = sc.get("kcalMax", 10 ** 9)
        price_max = sc.get("priceMax", 10 ** 9)
        protein_min = sc.get("proteinMin", 0)

        # 场景内筛选
        ok = [m for m in pool if m["price"] <= price_max and (m["kcal"] == 0 or m["kcal"] <= kcal_max)]
        if sc["id"] == "fitness":
            ok = [m for m in ok if m["protein"] >= protein_min]
        if not ok:
            ok = pool[:12]

        # 主食取自场景池；搭档（饮品/小食）在全菜单里挑，避免高蛋白筛选把低卡搭档过滤掉
        COMPANION_RE = {
            "breakfast": r"咖啡|牛奶|豆浆|果汁|茶|玉米",
            "office": r"咖啡|茶|可乐|薯|派|旋风|新地",
            "kids": r"牛奶|果汁|玉米|苹果",
            "fitness": r"无糖|咖啡|茶|玉米|沙拉|牛奶",
            "beauty": r"咖啡|茶|冰淇淋|旋风|新地",
        }
        cre = COMPANION_RE.get(sc["id"], r"咖啡|茶|可乐|薯")
        mains = ok
        companions = [m for m in menu if re.search(cre, m["name"]) and m["code"] not in
                      {x["code"] for x in mains}]
        if not companions:
            companions = [m for m in menu if m["code"] not in {x["code"] for x in mains}][:10]

        # 「全是饮品」的组合不成立（会推出「红茶 + 冰咖啡」这种）
        SOLID_RE = re.compile(r"堡|卷|饭|满分|粥|蛋|薯|翅|鸡|玉米|派|沙拉|盒|盒装")

        combos, seen = [], set()
        for m1 in mains[:8]:
            for m2 in companions[:12]:
                key = tuple(sorted({m1["code"], m2["code"]}))
                if key in seen:
                    continue
                seen.add(key)
                items = [m1, m2]
                total = sum(x["price"] for x in items)
                kc = sum(x.get("kcal", 0) for x in items)
                pr = sum(x.get("protein", 0) for x in items)
                if total > price_max:
                    continue
                if kc and kc > kcal_max:
                    continue
                if protein_min and pr < protein_min:
                    continue
                if not any(SOLID_RE.search(x["name"]) for x in items):
                    continue
                combos.append({
                    "items": [{"code": x["code"], "name": x["name"], "price": x["price"],
                               "kcal": x.get("kcal", 0)} for x in items],
                    "total": round(total, 2), "kcal": kc,
                    "protein": round(pr, 1),
                    "kcalKnown": all((x.get("kcal") or 0) > 0 for x in items),
                })

        # 兜底：实在凑不出两件套时，退化为单品推荐
        if not combos:
            for m1 in mains[:3]:
                combos.append({
                    "items": [{"code": m1["code"], "name": m1["name"], "price": m1["price"],
                               "kcal": m1.get("kcal", 0)}],
                    "total": round(m1["price"], 2), "kcal": m1.get("kcal", 0),
                    "protein": round(m1.get("protein", 0), 1),
                    "kcalKnown": (m1.get("kcal") or 0) > 0,
                })

        # 排序：热量数据完整的优先，再按场景指标
        if sc["id"] == "fitness":
            combos.sort(key=lambda c: (not c["kcalKnown"], -c["protein"], c["total"]))
        else:
            combos.sort(key=lambda c: (not c["kcalKnown"], c["kcal"] or 0, c["total"]))

        out.append({**sc, "count": len(pool), "bundles": combos[:3], "fallback": is_fallback})
    return out


# =============================================================================
# 提醒聚合：券过期 / 可领未领 / 积分过期 / 抽奖机会 / 奖品核销 / 活动日历
# =============================================================================
DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")


def parse_dt(s: str):
    if not s:
        return None
    m = DT_RE.search(s)
    if not m:
        return None
    v = m.group().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except Exception:
            continue
    return None


def build_reminders(coupons: list, available: list, account: dict,
                    lottery: dict, prizes: list, campaigns: list,
                    claimed_titles: set = None, codes_map: dict = None) -> list:
    rems = []
    now = datetime.now()
    claimed_titles = claimed_titles or set()
    codes_map = codes_map or {}

    # 1) 卡包中的券 —— 临近过期
    for c in coupons:
        valid = c.get("valid") or ""
        parts = re.split(r"\s*-\s*(?=\d{4}-)", valid)
        end = parse_dt(parts[-1]) if len(parts) > 1 else parse_dt(valid)
        if not end:
            continue
        days = (end - now).days
        if days < 0:
            continue
        if days <= 3:
            level = "danger"
        elif days <= 7:
            level = "warn"
        else:
            level = "info"
        rems.append({
            "level": level, "icon": "🎟️", "type": "券过期",
            "title": c.get("name", ""),
            "desc": (c.get("desc") or "") + f"　剩余 {days} 天",
            "deadline": end.strftime("%Y-%m-%d"), "days": days,
            "codes": codes_map.get(c.get("name", ""), []),
        })

    # 2) 可领取但尚未领取的券 —— 这是最容易错过的羊毛
    for a in available:
        title = a.get("title") or a.get("name") or ""
        if title and title not in claimed_titles:
            rems.append({
                "level": "warn", "icon": "🚨", "type": "待领券",
                "title": title, "desc": "当前可领取，尚未领取 —— 别错过",
                "deadline": "", "days": 0,
                "codes": codes_map.get(title, []),
            })

    # 3) 积分账户
    if account:
        exp_soon = to_int(account.get("currentMouthExpirePoint") or account.get("nextMouthExpirePoint"))
        avail = to_int(account.get("availablePoint"))
        if exp_soon > 0:
            rems.append({
                "level": "danger" if exp_soon >= 50 else "warn",
                "icon": "⭐", "type": "积分过期",
                "title": f"{exp_soon} 积分即将过期",
                "desc": "可用于麦麦商城兑换或积分抽奖，不用就浪费了",
                "deadline": "", "days": 0,
            })
        if avail > 0:
            rems.append({
                "level": "info", "icon": "💎", "type": "积分余额",
                "title": f"当前可用积分 {avail}",
                "desc": "可兑换商品券或参与积分抽奖",
                "deadline": "", "days": 0,
            })

    # 4) 抽奖活动
    if lottery:
        st = lottery.get("status") or {}
        if st.get("code") == "SUCCESS":
            decision = lottery.get("drawDecision") or {}
            nxt = decision.get("nextConsumption") or {}
            eligible = bool(decision.get("resourceEligible"))
            end = parse_dt(lottery.get("endTime") or "")
            end_txt = end.strftime("%Y-%m-%d") if end else ""
            if eligible:
                rems.append({
                    "level": "danger", "icon": "🎁", "type": "抽奖机会",
                    "title": f"{lottery.get('activityName','积分抽奖')}：可抽奖",
                    "desc": nxt.get("text") or "有可消耗的抽奖资源，及时参与",
                    "deadline": end_txt, "days": (end - now).days if end else 0,
                })
            else:
                rems.append({
                    "level": "info", "icon": "🎁", "type": "抽奖活动",
                    "title": lottery.get("activityName", "积分抽奖"),
                    "desc": f"{decision.get('reason') or '暂不满足条件'}｜{nxt.get('text') or ''}".strip("｜"),
                    "deadline": end_txt, "days": (end - now).days if end else 0,
                })

    # 5) 待核销奖品
    for p in (prizes or []):
        rems.append({
            "level": "warn", "icon": "🏆", "type": "奖品待用",
            "title": p.get("name", ""),
            "desc": "已中奖，记得在有效期内使用",
            "deadline": p.get("expireTime", ""), "days": 0,
        })

    # 6) 进行中的活动
    for cp in (campaigns or [])[:4]:
        rems.append({
            "level": "info", "icon": "📅", "type": "进行中活动",
            "title": cp.get("title", ""),
            "desc": (cp.get("desc") or "")[:60],
            "deadline": cp.get("date", ""), "days": 0,
        })

    order = {"danger": 0, "warn": 1, "info": 2}
    rems.sort(key=lambda r: (order.get(r["level"], 9), r["days"]))
    return rems


def parse_available(raw: str) -> list:
    """解析 available-coupons 的文本列表。
       接口自带「状态：已领取/未领取」字段，优先采用；
       接口未给状态时回退为 None，由 main() 用卡包/门店券交叉判定。"""
    out = []
    blocks = re.split(r"\n\s*-\s*优惠券标题：", raw)
    for b in blocks[1:]:
        lines = b.split("\n")
        title = lines[0].strip().rstrip("\\").strip()
        if not title:
            continue
        sm = re.search(r"状态：\s*(已领取|未领取)", b)
        st = sm.group(1) if sm else None
        out.append({"title": title, "claimed": (True if st == "已领取" else (False if st == "未领取" else None))})
    return out


def parse_mall_orders(raw: str) -> list:
    """解析 mall-order-list 文本中的订单摘要（orderId / 状态 / 件数 / 商品名）"""
    out = []
    for m in re.finditer(r"订单id[：:]\s*([A-Za-z0-9]+)", raw):
        oid = m.group(1)
        blk = raw[m.end(): m.end() + 600]
        st = re.search(r"订单状态[：:]\s*([^\n\\]+)", blk)
        ttl = re.search(r"订单状态主标题[：:]\s*([^\n\\]+)", blk)
        cnt = re.search(r"商品总数[：:]\s*(\d+)", blk)
        goods = re.findall(r"商品名称[：:]\s*([^\n\\,]+)", blk)
        out.append({
            "orderId": oid,
            "status": (st.group(1).strip() if st else ""),
            "statusTitle": (ttl.group(1).strip() if ttl else ""),
            "count": to_int(cnt.group(1)) if cnt else 0,
            "goods": [g.strip() for g in goods][:6],
        })
    return out


# 券标题 → 菜单关键词清洗：去价格前缀与促销后缀，留下核心商品词
TITLE_NOISE_RE = re.compile(r"^[\d.]+元|任选\d*|买一送一|第二份半价|免费|新人专享-|超值|人气")


def title_key(title: str) -> str:
    return TITLE_NOISE_RE.sub("", title or "").strip()


def title_to_codes(title: str, menu_names: dict, direct_match) -> list:
    """券标题（如「9.9元中杯冰美式」「免费脆薯饼」）→ 菜单编码列表，
       供「不错过提醒」点击后联动菜单选品。三段式：
       1) 清洗后直接匹配（互相包含）  2) 编码直配  3) 2-gram 相似度兜底"""
    key = title_key(title)
    if not key:
        return []
    out = direct_match(key)
    if out:
        return out[:4]
    # 2-gram 滑窗兜底：「脆薯饼」→「心形薯饼5块」
    kb = {key[i:i + 2] for i in range(len(key) - 1)}
    if not kb:
        return []
    scored = []
    for code, name in menu_names.items():
        hit = sum(1 for g in kb if g in name)
        if hit:
            scored.append((hit / len(kb), code))
    scored.sort(reverse=True)
    return [c for s, c in scored if s >= 0.3][:4]


def parse_campaigns(raw: str) -> list:
    """解析 campaign-calendar 的文本活动列表（按标题去重）"""
    out, seen = [], set()
    cur_date = ""
    for line in raw.splitlines():
        m = re.match(r"^#+\s*(\d{4}年\d{1,2}月\d{1,2}日.*)$", line.strip())
        if m:
            cur_date = m.group(1).strip()
            continue
        m = re.search(r"\*\*活动标题\*\*：(.+)", line)
        if m:
            title = m.group(1).strip()
            if title and title not in seen:
                seen.add(title)
                out.append({"date": cur_date, "title": title, "desc": ""})
    return out


# =============================================================================
# 主流程
# =============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="深圳市")
    ap.add_argument("--keyword", default="科技园")
    ap.add_argument("--store-code", default="")
    ap.add_argument("--store-name", default="")
    ap.add_argument("--claim", action="store_true",
                    help="先调用 auto-bind-coupons 一键领取全部可领券（写操作，需用户同意）")
    args = ap.parse_args()

    token = os.environ.get("MCD_MCP_TOKEN", "")
    if not token:
        raise SystemExit("错误: 未设置环境变量 MCD_MCP_TOKEN")

    if args.claim:
        raw_b = mcp_call("auto-bind-coupons", {}, token)
        m = re.search(r"总计:\s*(\d+)\s*张[\s\S]*?成功:\s*(\d+)\s*张[\s\S]*?失败:\s*(\d+)\s*张", raw_b)
        if m:
            print(f"[0/6] 一键领券: 总计 {m.group(1)} / 成功 {m.group(2)} / 失败 {m.group(3)}")
        else:
            print("[0/6] 一键领券: 已执行（未解析到统计）")

    # ---- 1. 定位门店 ----
    stores_out = []
    store_code, store_name = args.store_code, args.store_name
    if not store_code:
        raw = mcp_call("query-nearby-stores",
                       {"beType": 1, "searchType": 2, "city": args.city, "keyword": args.keyword},
                       token)
        data = ((extract_json(raw) or {}).get("data")) or []
        for st in data:
            stores_out.append({
                "id": str(st.get("storeCode", "")),
                "name": st.get("storeName", ""),
                "addr": st.get("address", ""),
                "dist": round((st.get("distance") or 0) / 1000, 2),
                "hours": f"{st.get('businessStartTime','')}-{st.get('businessEndTime','')}",
                "open": bool(st.get("businessStatus")),
                "lat": st.get("latitude") or 0,
                "lng": st.get("longitude") or 0,
            })
        if not stores_out:
            raise SystemExit("未查询到附近门店，请更换城市或关键词")
        store_code, store_name = stores_out[0]["id"], stores_out[0]["name"]
    else:
        stores_out.append({"id": store_code, "name": store_name or store_code, "addr": "",
                           "dist": 0, "hours": "", "open": True, "lat": 0, "lng": 0})

    print(f"[1/6] 门店: {store_name} ({store_code})，共 {len(stores_out)} 家")

    # ---- 2. 菜单 ----
    raw = mcp_call("query-meals", {"storeCode": store_code, "beType": 1, "orderType": 1}, token)
    mdata = ((extract_json(raw) or {}).get("data")) or {}
    cats, meal_map = mdata.get("categories") or [], mdata.get("meals") or {}
    print(f"[2/6] 菜单: {len(cats)} 分类 / {len(meal_map)} 餐品")

    # ---- 3. 门店券 ----
    raw_c = mcp_call("query-store-coupons", {"storeCode": store_code, "beType": 1, "orderType": 1}, token)
    cdata = ((extract_json(raw_c) or {}).get("data")) or []

    # 跨接口编码对齐：券接口的 productCode（商品中心编码）与菜单编码（门店售卖编码）
    # 是两套体系，直接按编码匹配会失败。先用编码精确匹配，失败时按名称回退匹配。
    menu_codes = set()
    for m0 in meal_map.keys():
        menu_codes.add(str(m0))
    menu_names = {}
    for cat in cats:
        for m0 in (cat.get("meals") or []):
            code = str(m0.get("code") or "")
            detail = meal_map.get(code) or {}
            if code and detail.get("name"):
                menu_names[code] = detail["name"]

    # SPEC_RE / core_name 使用模块级统一定义（此前此处有一份只去结尾规格词的旧版本，已移除）

    def match_menu_codes(product_name: str) -> list:
        """券的商品名（如「美式中杯」）→ 菜单编码列表（如 507411 麦咖啡™美式）"""
        key = SPEC_RE.sub("", product_name or "").replace("麦咖啡™", "").replace("™", "").strip()
        if not key:
            return []
        out = []
        for code, name in menu_names.items():
            flat = name.replace("麦咖啡™", "").replace("™", "")
            if key in flat or flat in key:
                out.append(code)
        return out

    coupons_out = []
    for c in cdata:
        products = c.get("products") or []
        apply_to, matched_by_name = [], []
        for p in products:
            pc = str(p.get("productCode") or "")
            if pc and pc in menu_codes:
                apply_to.append(pc)
            else:
                # 编码不在菜单中 → 名称回退匹配
                for mc in match_menu_codes(str(p.get("productName") or "")):
                    if mc not in apply_to:
                        matched_by_name.append(mc)
        apply_to += [mc for mc in matched_by_name if mc not in apply_to]
        coupons_out.append({
            "id": str(c.get("couponId") or ""),
            "code": str(c.get("couponCode") or ""),
            "name": c.get("title") or "",
            "desc": "、".join([str(p.get("productName")) for p in products]) or "全场通用",
            "applyTo": apply_to,
            "valid": c.get("tradeDateTime") or "",
            "codeMatched": len(matched_by_name) == 0 and bool(apply_to),
        })
    print(f"[3/6] 门店可用券: {len(coupons_out)} 张"
          f"（编码直配 {sum(1 for c in coupons_out if c['codeMatched'])}，"
          f"名称回退 {sum(1 for c in coupons_out if not c['codeMatched'] and c['applyTo'])}）")

    # ---- 3b. 营养 ----
    raw_n = mcp_call("list-nutrition-foods", {}, token)
    nutri = parse_nutrition(raw_n)
    print(f"[4/6] 营养: {len(nutri)} 条")

    # ---- 5. 提醒数据源 ----
    my_coupons = []
    raw_m = mcp_call("query-my-coupons", {}, token)
    mb = extract_json(raw_m) or {}
    # query-my-coupons 返回的是 markdown 文本，做轻量提取
    for m in re.finditer(r"^#+\s*(.+?)\s*$", raw_m, re.M):
        name = m.group(1).strip()
        if name.startswith("您的优惠券") or "共" in name:
            continue
        blk = raw_m[m.end(): m.end() + 400]
        dm = re.search(r"\*\*有效期\*\*[:：]\s*(.+)", blk)
        my_coupons.append({"name": name, "valid": (dm.group(1).strip() if dm else "")})

    available = parse_available(mcp_call("available-coupons", {}, token))

    # 已领取判定：优先用 available-coupons 自带的「状态」字段；
    # 接口未给状态时，回退为「标题出现在 卡包券 或 门店券 中」
    known_titles = {c.get("name", "") for c in my_coupons} | {c.get("title", "") for c in cdata}
    claimed_cnt = 0
    for a in available:
        if a.get("claimed") is None:
            a["claimed"] = (a.get("title") or "") in known_titles
        claimed_cnt += bool(a["claimed"])

    # 提醒点击 → 菜单选品映射（券标题 → 菜单编码）
    codes_map = {}
    for a in available:
        t = a.get("title") or ""
        codes_map[t] = title_to_codes(t, menu_names, match_menu_codes)
    for c in coupons_out:
        codes_map[c["name"]] = c.get("applyTo") or title_to_codes(c["name"], menu_names, match_menu_codes)

    # ---- 4b. 麦麦商城订单（mall-order-list + 前 10 单详情）----
    orders_out = []
    try:
        raw_o = mcp_call("mall-order-list", {"size": 10}, token)
        odata = ((extract_json(raw_o) or {}).get("data")) or []
        for grp in (odata if isinstance(odata, list) else []):
            for it in (grp.get("list") or []):
                oid = str(it.get("orderId") or "")
                if not oid:
                    continue
                row = {
                    "orderId": oid,
                    "statusTitle": it.get("orderStatusTitle") or "",
                    "status": to_int(it.get("orderStatus")),
                    "count": to_int(it.get("totalCount")),
                    "goods": [str(g.get("goodsName") or g.get("name") or "")
                              for g in (it.get("goods") or [])][:6],
                    "detail": None,
                }
                orders_out.append(row)
        # 详情：逐个查，最多 10 次（限流 600 次/分钟内安全）
        for row in orders_out[:10]:
            try:
                raw_d = mcp_call("mall-order-detail", {"orderId": row["orderId"]}, token)
                dd = (extract_json(raw_d) or {}).get("data")
                if dd:
                    row["detail"] = {
                        "statusTitle": dd.get("orderStatusTitle") or dd.get("statusTitle") or "",
                        "total": to_float(dd.get("payAmount") or dd.get("totalAmount") or dd.get("amount")),
                        "createdAt": dd.get("createTime") or dd.get("orderTime") or "",
                        "goods": [str(g.get("goodsName") or g.get("name") or "")
                                  for g in (dd.get("goods") or dd.get("goodsList") or [])][:8],
                    }
            except Exception:
                pass
    except Exception:
        orders_out = []

    account = ((extract_json(mcp_call("query-my-account", {}, token)) or {}).get("data")) or {}
    lottery = ((extract_json(mcp_call("query-lottery-info", {}, token)) or {}).get("data")) or {}
    prizes = (((extract_json(mcp_call("query-my-prizes", {}, token)) or {}).get("data")) or {}).get("prizes") or []
    campaigns = parse_campaigns(mcp_call("campaign-calendar", {}, token))
    print(f"[5/6] 提醒源: 卡包券 {len(my_coupons)} / 可领券 {len(available)}（其中已领 {claimed_cnt}）/ 积分 {account.get('availablePoint','0')} / 奖品 {len(prizes)} / 活动 {len(campaigns)}")

    # ---- 6. 组装 ----
    menu_out, seen = [], set()
    for cat in cats:
        cname = (cat.get("name") or "").replace("\n", "").strip()
        for m in (cat.get("meals") or []):
            code = str(m.get("code") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            d = meal_map.get(code) or {}
            name = d.get("name") or code
            n = match_nutrition(name, nutri) or {}
            item = {
                "code": code, "name": name, "cat": cname,
                "price": to_float(d.get("currentPrice")),
                "origin": to_float(d.get("originalPrice")),
                "kcal": to_int(n.get("energyKcal")),
                "kcalEstimated": bool(n.get("kcalEstimated")),
                "protein": round(to_float(n.get("protein")), 1),
                "fat": round(to_float(n.get("fat")), 1),
                "carb": round(to_float(n.get("carb")), 1),
                "sodium": to_int(n.get("sodium")),
                "image": d.get("image") or "",
                "tags": m.get("tags") or [],
                "discountType": d.get("discountType"),
            }
            item["scenes"] = classify_scenes(item)
            menu_out.append(item)

    # 场景化：给每个餐品打标签，并为每个场景生成推荐组合
    for m in menu_out:
        m["scenes"] = classify_scenes(m)
    scenes_out = build_scene_bundles(menu_out)

    matched = sum(1 for m in menu_out if m["kcal"] > 0)
    print(f"[6/6] 组装完成: {len(menu_out)} 餐品 / {matched} 条营养匹配")
    for s in scenes_out:
        tag = "兜底" if s.get("fallback") else "命中"
        print(f"      {s['icon']} {s['name']}: {s['count']} 品 / {len(s['bundles'])} 组合 [{tag}]")

    payload = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "store": {"code": store_code, "name": store_name},
        "stores": stores_out,
        "menu": menu_out,
        "coupons": coupons_out,
        "myCoupons": my_coupons,
        "available": available,
        "account": account,
        "lottery": lottery,
        "prizes": prizes,
        "orders": orders_out,
        "campaigns": campaigns,
        "scenes": scenes_out,
        "reminders": build_reminders(my_coupons, available, account, lottery, prizes, campaigns,
                                     claimed_titles=known_titles, codes_map=codes_map),
    }

    out = os.path.join(ROOT, "assets", "data.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write("/* 由 scripts/build_data.py 从麦当劳 MCP 真实返回生成，请勿手改 */\n")
        f.write("window.MCD_REAL_DATA = ")
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    print(f"已写入: {out}")


if __name__ == "__main__":
    main()
