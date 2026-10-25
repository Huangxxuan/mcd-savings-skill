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
import itertools
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

MCP_URL = "https://mcp.mcd.cn"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 这些状态码是「重试有意义」的：网关抖动 / 限流 / 上游超时
TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}


# =============================================================================
# MCP 调用
# =============================================================================
def _norm_token(token: str) -> str:
    """容错：允许用户把 `Bearer xxx` 整段贴进 MCD_MCP_TOKEN。

    本函数只负责去掉重复前缀 —— 脚本自己会加 `Bearer `，用户也带一个就会
    变成 `Bearer Bearer xxx`，服务端直接 401「当前鉴权码不存在或已失效」，
    排查成本极高（2026-10-25 实测踩到）。
    """
    t = (token or "").strip()
    while t.lower().startswith("bearer "):
        t = t[7:].strip()
    return t


def _post_with_retry(req, tool: str, fatal: bool = False, tries: int = 3):
    """带指数退避的 POST。

    只对「网络抖动 / 5xx / 429」重试；4xx（尤其 401 鉴权失败）立刻返回，
    重试再多次也没用，只会让用户多等。实测这台机器访问 mcp.mcd.cn 偶尔会
    出现连接重置，重试一次就过去了 —— 一次抖动不该让整份快照作废。
    """
    last = ""
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            if e.code == 401:
                msg = ("[MCP] HTTP 401 鉴权失败：" + detail.strip() + "\n"
                       "       检查 MCD_MCP_TOKEN：应为「原始 Token」，不要带 Bearer 前缀"
                       "（脚本会自己拼 Bearer）；也可能是 Token 已过期，重新获取后再试。")
                if fatal:
                    raise SystemExit(msg)
                print(msg.splitlines()[0])
                return {}
            last = f"HTTP {e.code}：{detail}"
            if e.code not in TRANSIENT_HTTP:
                break
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
        if i < tries - 1:
            wait = 2 ** i
            print(f"[MCP] {tool} 第 {i + 1} 次失败（{last}），{wait}s 后重试…")
            time.sleep(wait)
    msg = f"[MCP] {tool} 请求失败：{last}"
    if fatal:
        raise SystemExit(msg)
    print(msg)
    return {}


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
            "Authorization": f"Bearer {_norm_token(token)}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    body = _post_with_retry(req, tool, fatal=True)
    if "error" in body:
        raise SystemExit(f"[MCP] 工具 {tool} 调用失败：{body['error']}")
    content = body.get("result", {}).get("content", [])
    return content[0].get("text", "") if content else ""


def mcp_call_obj(tool: str, arguments: dict, token: str) -> dict:
    """返回 MCP 的 structuredContent（真正的结构化结果）。
       注意：mcp_call() 只取 content[0].text，而部分工具（query-my-coupons /
       available-coupons）的 text 是 markdown 列表、structuredContent 才是 JSON。
       早期版本用正则去 markdown 里抓券名，把 couponId / discountInfo /
       beTypes / tradeEndDate 这些决定「能不能用、能省多少」的字段全丢了 ——
       这就是「券信息与功能断裂」的根因。"""
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
    body = _post_with_retry(req, tool, fatal=False)
    if not body:
        return {}
    if "error" in body:
        print(f"[MCP] {tool} 调用失败：{str(body['error'])[:200]}")
        return {}
    res = body.get("result", {}) or {}
    sc = res.get("structuredContent")
    if isinstance(sc, dict) and sc:
        return sc
    # 回退：从 text 里抠 JSON
    content = res.get("content", []) or []
    if content:
        try:
            out = extract_json(content[0].get("text", ""))
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    return {}


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


def pick_num(obj: dict, keys, default=None):
    """从对象里按候选字段名取第一个数值；取不到返回 default。
    用于门店的配送费 / 起送门槛 / 免配送门槛 —— 不同 MCP 版本命名不一致，
    这里只做「有就读、没有就 None」，绝不生成兜底数字。"""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        if k in obj:
            v = obj[k]
            if isinstance(v, (int, float)) and v == v:  # 排除 NaN
                return float(v)
            try:
                s = str(v).replace("元", "").strip()
                if s:
                    return float(s)
            except Exception:
                continue
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
     "desc": "高蛋白控卡 · 方案蛋白 ≥ 25g · ≤ 550 kcal", "kcalMax": 550, "proteinMin": 25},
    {"id": "beauty", "name": "悦己养颜餐", "icon": "🌸",
     "desc": "犒赏自己的小甜头 · 目标 ≤ 400 kcal", "kcalMax": 400, "priceMax": 35},
]

# 场景池为空时的兜底说明（写进 data.js 的 scenes[].fallbackNote，页面直接显示）。
# 兜底不是错，但必须让用户看懂「为什么这个场景下没有专属商品」——
# 最典型的是早餐：麦当劳早餐只卖到约 10:30，正餐时段的菜单里根本没有早餐 SKU。
FALLBACK_NOTE = {
    "breakfast": "早餐供应时段（约 07:00–10:30）已过，当前菜单没有早餐 SKU；"
                 "以下是按「≤ 450 kcal 主食」给的替代，想看真早餐请在早上重跑一次快照",
    "office": "下午茶专属品不足，已按「一杯喝的 + 一份小食」兜底",
    "kids": "儿童套餐当前不可售，已按「小件 + 无糖饮」兜底",
    "fitness": "高蛋白单品不足，已按「蛋白 ≥ 15g 且 ≤ 550 kcal」兜底",
    "beauty": "甜品小食不足，已按「甜品 / 饮品」兜底",
}

# =============================================================================
# 套餐型 SKU：营养与价格的口径纠正（第 19 轮）
# =============================================================================
# 两个实测事实，决定了下面所有规则：
#
# ① **套餐的 kcal / protein 只等于主堡单品**。
#    板烧鸡腿堡四件套 391 = 板烧鸡腿堡 391；培根安格斯四件套 707 = 培根安格斯单品 707；
#    不素之霸四件套 493 = 不素之霸单品 493。薯条 + 可乐 + 派 一粒卡都没算进去。
#    直接当整份营养用，四件套会「虚低」约 600~700 kcal —— 健身/控卡场景就会把
#    一个 1000+ kcal 的套餐当成「539 kcal 高蛋白餐」推荐出去（用户当场发现）。
#
# ② **四件套/随心选的「菜单价」是麦金卡会员价**，划线价才是普通账号的结算价。
#    板烧四件套 菜单 28 / 划线 57，非会员按 57 收（calculate-price 实测）。
#    所以场景方案里「四件套 ¥28 + 奶铁 ¥13.9 = ¥41.9」对没开卡的账号是假的，
#    真实要付 ¥70.9。凡对外报价，一律用结算价，会员价只作为「有卡还能再省」的附注。
SET_RE = re.compile(r"两件套|四件套|三件套|套餐|乐园餐|随心选|双人餐|随心拼|拼盘|四宫格|七件任选")
SET_SUFFIX_RE = re.compile(r"(两件套|四件套|三件套|套餐|乐园餐|随心选|双人餐|随心拼|四宫格小食盘双人餐)$|（\d+件任选）$")
# 配餐基准：只用菜单里真实存在、且官方给了营养值的条目，不臆造数字
SET_PART_KEYS = ("fries", "coke", "pie")


def settle_price(m: dict) -> float:
    """真实结算价。麦金卡商品的菜单价是会员价，普通账号按划线价付款。

    标签不可靠：实测 9900016311「龙焰美味四件套」没打麦金卡标签，菜单 29 / 划线 57，
    核价仍按 57 收。所以「名字是四件套/随心选 且 划线价高于菜单价 20%」也判为会员价。
    """
    o = m.get("origin") or m["price"]
    if o <= m["price"]:
        return m["price"]
    if m.get("memberPrice") or m.get("member"):
        return o
    try:
        if MEMBER_NAME_RE.search(m["name"]) and o > m["price"] * 1.2:
            return o
    except NameError:
        pass
    return m["price"]


def set_part_size(name: str) -> int:
    """套餐里有几件：四件套=4，三件套/xx套餐=3，其余（随心选/双人餐/拼盘）构成不明=0"""
    if "四件套" in name:
        return 4
    if "三件套" in name:
        return 3
    if re.search(r"套餐$", name):
        return 3
    if re.search(r"乐园餐$", name):
        return 3
    if "两件套" in name:
        return 2
    return 0


def set_core(name: str) -> str:
    """套餐的主品名：板烧鸡腿堡四件套 → 板烧鸡腿堡。

    场景方案去重要用它 —— 否则「板烧单品 / 板烧四件套 / 板烧三件套」会被当成三个
    不同方案推给用户（实际是同一个堡换三种包装，用户已经指出过）。
    """
    base = SET_SUFFIX_RE.sub("", name or "").strip("（）() ")
    return core_name(base) or core_name(name or "")


def enrich_set_nutrition(menu: list) -> dict:
    """给套餐型 SKU 补上「配餐」的营养（估算），并如实标注来源。

    判定依据是硬证据而不是猜测：**套餐 kcal 与同名主堡单品的 kcal 完全相等**，
    就说明接口只算了主堡。已经按整份给的（如「500大卡套餐」495 kcal）绝不重复相加。

    补不出来的（随心选 / 双人餐 / 拼盘 —— 官方没说里面是什么）标 `setKcalPartial`，
    宁可显示「营养未含配餐」，也不编一个数字。
    """
    by_name = {}
    for m in menu:
        if not SET_RE.search(m["name"]):
            by_name.setdefault(m["name"], m)
    parts = {}
    for key, nm in (("fries", "薯条"), ("coke", "可乐"), ("pie", "派")):
        c = next((m for m in menu if m["name"] == nm and (m.get("kcal") or 0) > 0), None)
        if c:
            parts[key] = c

    stats = {"sets": 0, "estimated": 0, "official": 0, "partial": 0, "unknown": 0}
    for m in menu:
        if not SET_RE.search(m["name"]):
            continue
        stats["sets"] += 1
        m["setMeal"] = True
        if m.get("setKcalEstimated"):
            # 幂等：已经补过的不再相加（重复跑会出现 1059 + 668 = 1727 的滚雪球）
            stats["estimated"] += 1
            continue
        kcal = m.get("kcal") or 0
        if kcal <= 0:
            m["setKcalPartial"] = True
            stats["unknown"] += 1
            continue
        if re.search(r"大卡", m["name"] + str(m.get("cat") or "")):
            # 「500大卡套餐」这一类官方给的就是整份（牛气满满 495 / 苹板支撑 476），
            # 分类名里带「大卡」，光看餐品名会漏判成 partial
            m["setKcalOfficial"] = True
            stats["official"] += 1
            continue
        base = SET_SUFFIX_RE.sub("", m["name"]).strip("（）() ")
        single = by_name.get(base)
        if not single or (single.get("kcal") or 0) <= 0 or abs(kcal - single["kcal"]) > 2:
            m["setKcalPartial"] = True
            stats["partial"] += 1
            continue
        n = set_part_size(m["name"])
        keys = []
        if n >= 3:
            keys += ["fries", "coke"]
        if n >= 4:
            keys.append("pie")
        if not keys or any(k not in parts for k in keys):
            m["setKcalPartial"] = True
            stats["partial"] += 1
            continue
        add_kcal = sum(parts[k]["kcal"] for k in keys)
        add_pro = sum(parts[k].get("protein") or 0 for k in keys)
        m["kcalOfficialMain"] = kcal
        m["kcal"] = kcal + add_kcal
        m["protein"] = round((m.get("protein") or 0) + add_pro, 1)
        m["fat"] = round((m.get("fat") or 0) + sum(parts[k].get("fat") or 0 for k in keys), 1)
        m["carb"] = round((m.get("carb") or 0) + sum(parts[k].get("carb") or 0 for k in keys), 1)
        m["setKcalEstimated"] = True
        m["setParts"] = [f"{parts[k]['name']} {parts[k]['kcal']}" for k in keys]
        m["setNote"] = (f"官方只给主堡 {kcal} kcal，余下按菜单 "
                        f"{' + '.join(m['setParts'])} 估算")
        stats["estimated"] += 1
    return stats


BREAKFAST_RE = re.compile(r"早餐|麦满分|粥|豆浆|早安|晨")
OFFICE_RE = re.compile(r"咖啡|美式|拿铁|奶铁|卡布|茶|可乐|雪碧|薯条|派|麦旋风|新地|冰淇淋|圆筒|阳光柠檬")
KIDS_RE = re.compile(r"开心乐园|儿童|牛奶|苹果片|玉米|果汁|迷你|FUN")
FITNESS_RE = re.compile(r"板烧|吉士|鸡胸|沙拉|牛肉|鳕鱼|麦满分|蛋")
BEAUTY_RE = re.compile(r"冰淇淋|新地|麦旋风|派|圆筒|甜品|蛋糕|草莓|朱古力|香芋|菠萝|布丁|红豆|奶茶")


def classify_scenes(it: dict) -> list:
    """给单个餐品打场景标签（可多标签）

    注意 `hay` 与 `hay_nocat` 的区别：**「悦己养颜」绝不能用分类名判断**。
    菜单里有一整个分类叫「小食甜品/其他」，一匹配「甜品」两个字，薯条、鸡块、
    酱料全被打上养颜标签，方案就会推「薯条 + 锡兰红茶」给想犒赏自己的人。
    所以 beauty 只看餐品名与标签。
    """
    hay = f"{it.get('name','')} {it.get('cat','')} {' '.join(it.get('tags') or [])}"
    hay_nocat = f"{it.get('name','')} {' '.join(it.get('tags') or [])}"
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

    if BEAUTY_RE.search(hay_nocat) and kcal <= 400:
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
    """为每个场景生成 3 套推荐方案。

    第 19 轮修的三条，全部来自用户实测反馈：
      ① **套餐不再配饮品**。四件套/三件套本身已经含饮料，再叠一杯奶铁就是重复点单
         （图里「板烧四件套 ¥28 + 麦咖啡奶铁 ¥13.9」正是这个问题）。套餐单独成方案。
      ② **报价一律用结算价**。四件套菜单 28 是麦金卡会员价，没卡的账号按 57 结算，
         场景里写「合计 ¥41.90」会让人以为 42 块真能吃四件套 + 拿铁。
      ③ **三个方案必须真的不同**。旧版会给出「板烧单品 / 板烧四件套 / 板烧三件套」配同一杯
         奶铁 —— 同一个堡换三种包装，卡路里还完全一样（因为套餐营养只算了主堡）。
         现在按「主品 core 名 + 件数」去重，同一主品只留一条。
    """
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

        def sp(m):
            return settle_price(m)

        def nut(m):
            return m.get("kcal") or 0

        # 场景内筛选：价格按结算价判断，热量按补全后的值判断
        ok = [m for m in pool
              if sp(m) <= price_max and (nut(m) == 0 or nut(m) <= kcal_max)]
        if sc["id"] == "fitness":
            ok = [m for m in ok if (m.get("protein") or 0) >= protein_min]
        if not ok:
            ok = pool[:12]

        # 主食取自场景池；搭档（饮品/小食）在全菜单里挑，避免高蛋白筛选把低卡搭档过滤掉
        COMPANION_RE = {
            "breakfast": r"咖啡|牛奶|豆浆|果汁|茶|玉米",
            "office": r"咖啡|茶|可乐|薯|派|旋风|新地",
            "kids": r"牛奶|果汁|玉米|苹果",
            # 健身的搭档必须低糖：奶铁 / 拿铁 / 雪顶 / 新地 不进健身方案
            "fitness": r"无糖|美式|纯牛奶|牛奶|玉米|沙拉|茶",
            "beauty": r"咖啡|茶|冰淇淋|旋风|新地",
        }
        cre = COMPANION_RE.get(sc["id"], r"咖啡|茶|可乐|薯")
        scene_codes = {m["code"] for m in pool}
        hit = [m for m in menu if re.search(cre, m["name"])]
        # 同场景优先：搭档必须尽量来自本场景池，否则会出现「办公下午茶方案里塞一个
        # 只打了 beauty 标签的商品」——前端应用方案后在本场景菜单里根本定位不到它。
        companions = [m for m in hit if m["code"] in scene_codes] + \
                     [m for m in hit if m["code"] not in scene_codes]
        if not companions:
            companions = menu[:10]

        # 「全是饮品」的组合不成立（会推出「红茶 + 冰咖啡」这种）
        SOLID_RE = re.compile(r"堡|卷|饭|满分|粥|蛋|薯|翅|鸡|玉米|派|沙拉|盒|盒装")
        DRINK_RE = re.compile(r"咖啡|奶铁|拿铁|美式|茶|可乐|雪碧|果汁|豆浆|牛奶|奶(?:$|[（(])|雪冰|饮品")
        FATTY_DRINK_RE = re.compile(r"奶铁|拿铁|雪顶|新地|星冰乐|奶茶|焦糖|摩卡|朱古力")

        SWEET_RE = re.compile(r"派|冰淇淋|新地|旋风|圆筒|蛋糕|布丁|雪冰|奶茶|可可|朱古力|薯饼")
        FRUIT_RE = re.compile(r"苹果|橙|柠檬|菠萝|芒果|草莓|葡萄|蜜桃|莓")
        set_meals = [m for m in ok if m.get("setMeal")]
        mains = [m for m in ok if not m.get("setMeal")]
        combos = []

        def push(items, kind):
            total = sum(sp(x) for x in items)
            kc = sum(x.get("kcal") or 0 for x in items)
            pr = sum(x.get("protein") or 0 for x in items)
            if total > price_max:
                return
            if kc and kc > kcal_max:
                return
            if protein_min and pr < protein_min:
                return
            # 悦己养颜：方案里必须真有一件甜品，否则会变成「薯条 + 红茶」那种下午茶答案
            if sc["id"] == "beauty" and not any(SWEET_RE.search(x["name"]) for x in items):
                return
            notes = [x["setNote"] for x in items if x.get("setNote")]
            combos.append({
                "kind": kind,
                "items": [{"code": x["code"], "name": x["name"],
                           "price": round(sp(x), 2), "kcal": x.get("kcal") or 0,
                           "protein": round(x.get("protein") or 0, 1),
                           "memberOnly": sp(x) > x["price"] + 1e-9} for x in items],
                "total": round(total, 2), "kcal": kc, "protein": round(pr, 1),
                "kcalKnown": all((x.get("kcal") or 0) > 0 for x in items),
                "kcalEstimated": any(x.get("setKcalEstimated") for x in items),
                "estNote": notes[0] if notes else "",
                "setCount": sum(1 for x in items if x.get("setMeal")),
            })

        # ① 套餐：本身就是一顿完整的饭（堡 + 薯条 + 饮料 [+ 派]），单独成方案
        for m in set_meals[:8]:
            push([m], "set")

        # ② 主食 + 搭档（搭档不能是套餐，也不能是同一品类）
        for m1 in mains[:8]:
            for m2 in companions[:12]:
                if m1["code"] == m2["code"]:
                    continue
                if m1.get("cat") == m2.get("cat"):
                    continue
                if m2.get("setMeal"):
                    continue
                if sc["id"] == "fitness" and FATTY_DRINK_RE.search(m2["name"]):
                    continue
                items = [m1, m2]
                if not any(SOLID_RE.search(x["name"]) for x in items):
                    continue
                if all(DRINK_RE.search(x["name"]) for x in items):
                    continue
                # 同一颗水果点两次不算两件：苹果片 + 100% 苹果汁 → 跳过
                fruits = [{w for w in FRUIT_RE.findall(x["name"])} for x in items]
                if fruits[0] and fruits[0] == fruits[1]:
                    continue
                push(items, "combo")

        # 兜底：实在凑不出方案时，退化为单品推荐
        if not combos:
            for m1 in mains[:3]:
                push([m1], "single")

        # 排序：套餐优先 → 营养齐全 → 场景指标。
        # 「套餐优先」这条是必须的：儿童套餐场景里真实的「鱼排堡开心乐园餐 ¥24」
        # 热量待核，只按 kcalKnown 排序会被「苹果片 + 苹果汁」挤到第四位，用户看不到真套餐。
        def kind_rank(c):
            return {"set": 0, "combo": 1, "single": 2}.get(c["kind"], 3)

        def drink_first(c):
            """办公下午茶要「一杯喝的」当主体；甜品只是搭配。
            不加这条，它和悦己养颜都会给「派 + 红茶」，两个场景等于没区别。"""
            if sc["id"] != "office":
                return 0
            return 0 if DRINK_RE.search(c["items"][0]["name"]) else 1

        if sc["id"] == "fitness":
            combos.sort(key=lambda c: (kind_rank(c), not c["kcalKnown"], -c["protein"], c["total"]))
        else:
            combos.sort(key=lambda c: (kind_rank(c), drink_first(c),
                                       not c["kcalKnown"], c["kcal"] or 0, c["total"]))

        # ③ 三个方案按「主品 core 名 + 件数」去重：同一主品换包装不算新方案
        ranked, used = [], set()
        for c in combos:
            key = (set_core(c["items"][0]["name"]), len(c["items"]))
            if key in used:
                continue
            used.add(key)
            ranked.append(c)
            if len(ranked) == 3:
                break
        if len(ranked) < 3:
            # 主品不够 3 种时（例如甜品本店只有「派」和「奶香大米派」两款），
            # 放宽到「同一主品 + 不同搭档」，而不是硬凑出重复方案或直接少一个。
            used_pairs = {(set_core(c["items"][0]["name"]),
                           tuple(sorted(x["code"] for x in c["items"]))) for c in ranked}
            for c in combos:
                if any(c is x for x in ranked):
                    continue
                key = (set_core(c["items"][0]["name"]),
                       tuple(sorted(x["code"] for x in c["items"])))
                if key in used_pairs:
                    continue
                used_pairs.add(key)
                ranked.append(c)
                if len(ranked) == 3:
                    break
        combos = ranked

        # 组合里用到的商品若尚未打本场景标签就补上 —— 保证「方案里的商品一定能
        # 在本场景菜单里找到」，否则前端点方案后既看不到也取消不了（真实踩过的坑）
        for c in combos[:3]:
            for it in c["items"]:
                for m in menu:
                    if m["code"] == it["code"] and sc["id"] not in (m.get("scenes") or []):
                        m.setdefault("scenes", []).append(sc["id"])
                        m["sceneFallback"] = True
        count_now = sum(1 for m in menu if sc["id"] in (m.get("scenes") or []))

        # 兜底时要把「为什么兜底」说清楚。只说「当前时段无专属商品」等于没解释：
        # 用户看到「健康早餐」下面摆着板烧鸡腿堡，会以为我们算错了 —— 其实是
        # 麦当劳早餐只卖到约 10:30，正餐时段根本没有早餐 SKU 可卖。
        out.append({**sc, "count": count_now, "bundles": combos[:3], "fallback": is_fallback,
                    "fallbackNote": FALLBACK_NOTE.get(sc["id"], "") if is_fallback else ""})
    return out


# =============================================================================
# 省钱榜单引擎
# 只使用 MCP 真实返回的字段：price（现价）/ origin（划线原价）/ kcal / protein
# 以及券 Title 里解析出的规则。任何算不出来的情况都留空，不编造。
# =============================================================================
DRINK_CATS = ("饮品", "麦咖啡™")
MAIN_RE = re.compile(r"堡|卷|饭|满分|粥|鸡排|麦乐鸡|套餐|四件套|三件套|随心选|随心配|拼")
NON_FOOD_RE = re.compile(r"徽章|周边|玩具|卡片|马克杯|杯垫|袋子")
# 酱料 / 调味包不是「吃到的东西」，不能拿来凑组合，否则 20 元档会被答成「鸡排 + 一包酱」
SAUCE_RE = re.compile(r"酱|调味|糖浆|配料")
# 「四件套 / 随心选」这一族在菜单里给的是麦金卡会员价（实测：龙焰美味四件套菜单 29，
# calculate-price 无券核价 57、discount 0；人气超值四件套随心选 28 → 57 同理）。
# query-meals 的麦金卡标签并不总打全（9900016311 就没打），所以这里用名字兜一层。
MEMBER_NAME_RE = re.compile(r"四件套|随心选")
PICK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元\s*(.{1,8}?)任选\s*(\d+)")


def parse_coupon_rule(c: dict) -> dict:
    """把券标题解析成可计算的规则（仅作「没有核价结果时」的兜底估算）。

    ⚠️ 关键：券的可用 SKU 有两个来源 —— `applyTo`（券适用商品，可能是品类 or 旧 SKU）
    与 `skus`（calculate-price 真正吃下的那个 SKU）。两者常常不一致，实测：
    「9.9元中杯冰美式」applyTo=[507411]、skus=[9900000119]；
    「新人专享-中杯美式7折」applyTo=[507411]、skus=[9900000119]；
    「新人专享-中杯奶铁7折」applyTo=[507409,510479]、skus=[9900000117]。
    真实的那个是 `skus`，所以这里把两边并起来，宁可多算一次核价，也不漏掉可用 SKU。
    """
    t = (c.get("name") or c.get("title") or "").strip()
    applies = [x for x in (c.get("applyTo") or []) if x]
    applies += [s.get("code") for s in (c.get("skus") or []) if s and s.get("code")]
    applies = list(dict.fromkeys(applies))  # 去重且保持顺序
    m = re.search(r"满\s*(\d+(?:\.\d+)?)\s*减\s*(\d+(?:\.\d+)?)", t)
    if m:
        return {"type": "threshold", "min": float(m.group(1)), "value": float(m.group(2)), "label": t}
    m = PICK_RE.search(t)
    if m:
        return {"type": "pick", "price": float(m.group(1)), "kw": m.group(2), "n": int(m.group(3)),
                "applies": applies, "label": t}
    m = re.search(r"(\d+(?:\.\d+)?)\s*折", t)
    if m:
        return {"type": "percent", "rate": float(m.group(1)) / 10, "applies": applies, "label": t}
    m = re.search(r"(?:减|省|立减)\s*(\d+(?:\.\d+)?)\s*元", t)
    if m:
        return {"type": "amount", "value": float(m.group(1)), "applies": applies, "label": t}
    m = re.search(r"^(\d+(?:\.\d+)?)\s*元", t)
    if m:
        return {"type": "fixed", "value": float(m.group(1)), "applies": applies, "label": t}
    if re.search(r"免费|0\s*元", t):
        return {"type": "free", "applies": applies, "label": t}
    return {"type": "unknown", "label": t}


def coupon_discount(rule: dict, items: list) -> float:
    """给定一份点单（items: [{code,name,price}]），算这张券能抵多少钱"""
    sub = sum(i["price"] for i in items)
    codes = {i["code"] for i in items}
    t = rule["type"]
    if t == "threshold":
        return rule["value"] if sub >= rule["min"] else 0.0
    if t == "percent":
        if rule["applies"]:
            return sum(i["price"] for i in items if i["code"] in rule["applies"]) * (1 - rule["rate"])
        return sub * (1 - rule["rate"])
    if t == "amount":
        if rule["applies"] and not (codes & set(rule["applies"])):
            return 0.0
        return rule["value"]
    if t == "fixed":
        if not rule["applies"]:
            return 0.0
        d = 0.0
        for i in items:
            if i["code"] in rule["applies"]:
                d = max(d, i["price"] - rule["value"])
        return max(0.0, d)
    if t == "pick":
        # 「N 元任选 M 件」只能从**这张券允许的 SKU**里挑，不能按名字关键字捞。
        # 老逻辑用 kw 匹配全菜单，把不在券范围内的商品也算进「任选」，
        # 实测「19.9元王牌炸鸡任选2」被凑成 王牌炸鸡(23.8)+薄皮焦香V翅(16)=39.8，
        # 页面报 39.8→19.9 省 19.9，而接口真实只把 23.8 打成 19.9，实付 35.9、省 3.9 —— 虚报 16 元。
        elig = set(rule.get("applies") or [])
        pool = [i for i in items if (not elig or i["code"] in elig)]
        if len(pool) < rule["n"]:
            return 0.0
        top = sorted(pool, key=lambda x: -x["price"])[:rule["n"]]
        return max(0.0, sum(i["price"] for i in top) - rule["price"])
    if t == "free":
        if not rule["applies"]:
            return 0.0
        prices = [i["price"] for i in items if i["code"] in rule["applies"]]
        return min(prices) if prices else 0.0
    return 0.0


def best_coupon(rules: list, items: list):
    """返回 (抵扣金额, 券标题)；无可用券时返回 (0, '')"""
    best, name = 0.0, ""
    for r in rules:
        d = coupon_discount(r, items)
        if d > best + 1e-9:
            best, name = d, r["label"]
    return round(best, 2), name


# =============================================================================
# 券后最省：只认 calculate-price 的真实核价结果
#
# 设计原因（实测踩过的坑）：
#   ① 券 Title 解析不出面额 → 「1024"码"力翻倍」真实省 13.52（34→20.48）却被当成 unknown 丢掉，
#      榜单里最省的一张券直接消失；
#   ② 券 Title 能解析、但适用 SKU 猜错 → 「19.9元王牌炸鸡任选2」被凑成 39.8 的篮子，
#      报「省 19.9」，接口真实只把 23.8 打成 19.9，实付 35.9、省 3.9，虚报 16 元；
#   ③ 「7 折」对错了商品 → 奶铁 13.9 算 4.17 折扣，接口返回 600012 促销规则不支持该商品。
# 所以这里改成：券的抵扣额一律取 calculate-price 返回的 realDiscount，
# 券只作用在它核价时真正吃下的 SKU 上（skus[].code），Title 仅用于展示文案。
# 没有核价结果的券，宁可不进榜，也不猜。
# =============================================================================

def coupon_window(c: dict):
    """解析券的生效区间。valid 有两种格式并存，必须都吃：
       门店券 "2026-10-19 10:30:00-2026-10-23 23:59:59"；卡包券 "2026-10-19~2026-10-23"。
    valid 缺失时退回 tradeStartDate / tradeEndDate。"""
    v = (c.get("valid") or "").strip()
    stamps = DT_RE.findall(v) if v else []
    if len(stamps) >= 2:
        return parse_dt(stamps[0]), parse_dt(stamps[-1])
    s, e = c.get("tradeStartDate"), c.get("tradeEndDate")
    return (parse_dt(s) if s else None), (parse_dt(e) if e else None)


def coupon_valid_now(c: dict, now: datetime = None):
    """这张券「此刻」能不能用，返回 (bool, 原因)。

    ★ 为什么必须在这一层判：realOk/realPay 是**抓取那一刻**调 calculate-price 的结论，
      快照一过夜，券可能已经过期，但核价结论还躺着。
      榜单若照抄，就会出现「榜单挂 ¥11.9，点下去 ¥22.5」——页面层之前靠 rankRowLive 打补丁，
      根因在这里：生成榜单时根本没看时间。
    """
    now = now or datetime.now()
    s, e = coupon_window(c)
    if s and now < s:
        return False, "not_started"
    if e:
        # tradeEndDate 只有日期，按「当天最后一秒」算，不然 23:00 就把当天券判死
        e2 = e if (e.hour or e.minute or e.second) else e.replace(hour=23, minute=59, second=59)
        if now > e2:
            return False, "expired"
    return True, ""


def verified_coupon_rules(coupons: list, by_code: dict, only_valid: bool = True) -> list:
    """把已核价成功的券转成「按 SKU 生效的固定抵扣」规则列表。

    only_valid=True 时按**生成时刻**再复核一次有效期：过期/未生效的券不进榜。
    否则快照里那些隔天就死的券会一直挂在榜单上，金额全是假的。
    """
    out = []
    for c in coupons or []:
        if not c.get("realOk"):
            continue
        if only_valid and not coupon_valid_now(c)[0]:
            continue
        pay = to_float(c.get("realPay"))
        orig = to_float(c.get("realOrig"))
        disc = to_float(c.get("realDiscount"))
        if pay <= 0 or orig <= 0 or disc <= 0.009:
            continue
        codes = [s.get("code") for s in (c.get("skus") or []) if s and s.get("code")]
        codes = [x for x in codes if x in by_code]
        if not codes:
            continue
        # 核价原价必须和菜单对得上（现价或划线价任一），否则说明快照漂移，宁可不上榜。
        # 例：麦咖啡™美式 现价 11.9 / 划线 19，9.9 券的 realOrig 是 19 —— 属于划线价口径。
        base_now = sum(by_code[x]["price"] for x in codes)
        base_ori = sum((by_code[x].get("origin") or by_code[x]["price"]) for x in codes)
        if min(abs(base_now - orig), abs(base_ori - orig)) > 0.02:
            continue
        out.append({
            "codes": set(codes),
            "discount": round(disc, 2),
            "pay": round(pay, 2),
            "orig": round(orig, 2),
            "name": (c.get("name") or "").strip(),
        })
    # 同一张券可能同时出现在「我的卡包 / 门店券 / 可领券」三个来源，按 (SKU, 券名, 到手价) 去重
    uniq, seen = [], set()
    for r in sorted(out, key=lambda x: -x["discount"]):
        k = (tuple(sorted(r["codes"])), r["name"], r["pay"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def best_verified_coupon(vrules: list, items: list):
    """返回 (抵扣金额, 券名)。

    抵扣额必须按**当前篮子里的现价**算，不能直接用券的 realDiscount ——
    realDiscount 是相对「原价（可能含划线价）」的优惠，而组合行的 origin 是现价之和，
    直接相减会把官方直降重复算一遍（实测：美式现价 11.9 / 划线 19，
    9.9 券 realDiscount=9.1，套到 11.9 的篮子上会多算 7.1 元）。
    正确口径：抵扣 = Σ(券管的那个 SKU 现价) − 券后价。
    """
    best, name = 0.0, ""
    for r in vrules:
        hits = [i for i in items if i["code"] in r["codes"]]
        if not hits:
            continue
        d = sum(i["price"] for i in hits) - r["pay"]
        if d > best + 1e-9:
            best, name = d, r["name"]
    return round(max(0.0, best), 2), name


def _row(items: list, origin: float, save: float, coupon: str, note: str = "", kind: str = "single"):
    pay = max(0.0, origin - save)
    kcal = sum(i.get("kcal") or 0 for i in items)
    protein = sum(i.get("protein") or 0 for i in items)
    known = all((i.get("kcal") or 0) > 0 for i in items)
    # 麦金卡商品：菜单价是会员价，没有该权益的账号按划线价结算（实测 28→57、62.9→122.5）。
    # 榜单必须能一眼看出「这个价需要麦金卡」，否则非会员会以为 29 元真的能省下来。
    member_gap = sum(max(0.0, (i.get("origin") or i["price"]) - i["price"])
                     for i in items if i.get("member"))
    row = {
        "items": [{"code": i["code"], "name": i["name"], "price": i["price"],
                   "kcal": i.get("kcal") or 0} for i in items],
        "origin": round(origin, 2), "pay": round(pay, 2), "save": round(save, 2), "kind": kind,
        "savePct": round(save / origin * 100) if origin > 0 else 0,
        "kcal": kcal, "kcalKnown": known, "protein": round(protein, 1),
        "kcalEstimated": any(i.get("setKcalEstimated") for i in items),
        "setCount": sum(1 for i in items if i.get("setMeal")),
        "setNote": next((i["setNote"] for i in items if i.get("setNote")), ""),
        "perYuanKcal": round(kcal / pay, 1) if pay > 0 and kcal > 0 else 0,
        "perYuanProtein": round(protein / pay, 2) if pay > 0 and protein > 0 else 0,
        "coupon": coupon, "note": note,
    }
    if member_gap > 0.009:
        row["memberOnly"] = True
        row["nonMemberPay"] = round(pay + member_gap, 2)
    return row


def _item(m: dict) -> dict:
    """把菜单项压缩成算价需要的字段（protein 必须带上，否则蛋白榜会全部算成 0）"""
    origin = m.get("origin") or m["price"]
    member = bool(m.get("memberPrice") and origin > m["price"])
    if not member and origin > m["price"] * 1.2 and MEMBER_NAME_RE.search(m["name"]):
        # 四件套 / 随心选一族：菜单价是会员价，标签可能缺失，名字兜一层
        member = True
    return {"code": m["code"], "name": m["name"], "price": m["price"],
            "kcal": m.get("kcal") or 0, "protein": m.get("protein") or 0,
            "origin": origin, "member": member,
            # 套餐营养的来源要能传到页面：估算值必须带 *，否则用户会当成官方数字
            "setMeal": bool(m.get("setMeal")),
            "setKcalEstimated": bool(m.get("setKcalEstimated")),
            "setKcalPartial": bool(m.get("setKcalPartial")),
            "setNote": m.get("setNote") or ""}


def build_savings(menu: list, coupons: list) -> dict:
    """生成省钱榜单：券后最省 / 官方直降 / 每元管饱 / 每元蛋白 / 套餐最优"""
    rules = [parse_coupon_rule(c) for c in coupons]
    by_code = {m["code"]: m for m in menu}
    vrules = verified_coupon_rules(coupons, by_code)
    food = [m for m in menu if not NON_FOOD_RE.search(m["name"]) and (m["price"] or 0) > 0]

    # ---------- 券后最省 ----------
    # 有核价结果时：一条券一条，金额全部来自 calculate-price，绝不用 Title 猜。
    # 没有核价结果时（例如别人只拿走了 data.js 没有 coupons 明细）：退回 Title 估算，并在 note 里标明。
    coupon_rows = []
    if vrules:
        for r in vrules:
            items = [_item(by_code[c]) for c in sorted(r["codes"]) if c in by_code]
            if not items:
                continue
            note = (f"「{r['name']}」券后 ¥{r['pay']:.2f}，省 {r['discount']:.2f} 元"
                    f"（calculate-price 已核价）")
            coupon_rows.append(_row(items, r["orig"], r["discount"], r["name"], note, "coupon"))
    else:
        for m in food:
            items = [_item(m)]
            save, cname = best_coupon(rules, items)
            if save > 0:
                coupon_rows.append(_row(items, m["price"], save, cname,
                                        f"用「{cname}」券后 ¥{max(0, m['price'] - save):.2f}，省 {save:.1f} 元（按券名估算）"))
    coupon_rows.sort(key=lambda r: (-r["save"], -r["savePct"]))

    # ---------- 单项：官方直降（划线价） ----------
    # 麦金卡商品的「划线价 → 菜单价」不是官方直降，是会员价；非会员结算仍是划线价。
    # 所以这类行标 memberOnly + nonMemberPay，并排在真正的公开直降之后。
    drop_rows = []
    for m in food:
        origin = m.get("origin") or 0
        if origin > m["price"] > 0:
            it = _item(m)
            is_member = it["member"]
            note = (f"麦金卡会员价 ¥{m['price']}（非会员 ¥{origin}）" if is_member
                    else f"官方直降 {round((origin - m['price']) / origin * 100)}%，省 {origin - m['price']:.1f} 元")
            drop_rows.append(_row([it], origin, origin - m["price"], "", note))
    drop_rows.sort(key=lambda r: (r.get("memberOnly", False), -r["savePct"], -r["save"]))

    # ---------- 单项：每元管饱 / 每元蛋白 ----------
    def unit_row(m, txt):
        """单品的「每元 X」行。麦金卡商品必须按结算价算 —— 用会员价 28 去除 1059 kcal，
        得出 37.8 kcal/元 是虚高近一倍，非会员照这个下单会当场对不上账。"""
        sp = settle_price(m)
        it = _item(m)
        if sp > it["price"] + 1e-9:
            it["price"] = sp
            it["origin"] = sp
            it["member"] = False
            txt += "（按非会员结算价）"
        return _row([it], sp, 0, "", txt)

    kcal_rows = sorted([unit_row(m, f"{m['kcal']} kcal ÷ ¥{settle_price(m)} = "
                                    f"{m['kcal'] / settle_price(m):.1f}")
                        for m in food if (m.get("kcal") or 0) > 0],
                       key=lambda r: -r["perYuanKcal"])
    protein_rows = sorted([unit_row(m, f"{round(m['protein'], 1)}g 蛋白 ÷ ¥{settle_price(m)} = "
                                       f"{m['protein'] / settle_price(m):.2f}")
                           for m in food if (m.get("protein") or 0) > 0],
                          key=lambda r: -r["perYuanProtein"])

    # ---------- 组合：单品 / 主食+小食 / 主食+饮品 / 三件套 / 多人拼单 ----------
    # 旧版这里用「mains <= 45」「origin > 50」「origin > 55」「pay <= 45」四处硬编码，
    # 把两端挖成了空档：菜单最低 3 元却一个都进不了套餐榜（≤20 永远为空），
    # 最贵单品 72.5 也永远上不了 100 元档。
    # 现在全价位都生成，由下面的 budgets 分档「挑」最优 —— 预算是挑出来的，不是砍出来的。
    # 散点池一律排除套餐型 SKU：套餐本身已经含饮品/小食，
    # 再拿它当"主食"配一杯可乐就是重复点单（用户实测指出过「四件套 + 奶铁」）。
    mains = [m for m in food
             if MAIN_RE.search(m["name"]) and m["cat"] not in DRINK_CATS
             and not SET_RE.search(m["name"])]
    drinks = [m for m in food if m["cat"] in DRINK_CATS and not SET_RE.search(m["name"])]
    sides = [m for m in food if m["cat"] not in DRINK_CATS
             and not MAIN_RE.search(m["name"]) and m["price"] <= 15
             and not SAUCE_RE.search(m["name"]) and not SET_RE.search(m["name"])]
    set_codes = {m["code"] for m in food if m.get("setMeal")}
    main_codes = {m["code"] for m in mains} | set_codes
    drink_codes = {m["code"] for m in drinks}
    all_rows = []

    def combo_coupon(items):
        """组合里能用的券：优先用核价过的券（抵扣额真实），没有核价结果才退回 Title 估算。"""
        if vrules:
            return best_verified_coupon(vrules, items)
        return best_coupon(rules, items)

    def add(items, kind, settle=False):
        """加入候选池。kcal=0（热量待核）的行照样保留 —— 旧版用 r["kcal"] > 0 一刀切，
        等于把 55 个「待核」商品从榜单里全部除名，这也是榜单只剩 24 行的原因之一。

        settle=True：麦金卡商品按**结算价**记账（四件套 28 → 57），并且原价取划线价合计，
        这样「比单点省多少」能算出来 —— 100 元以上那档如果只显示「省 ¥2（券）」，
        用户会以为套餐白买了。
        """
        its = [_item(m) for m in items]
        if settle:
            # 只用**划线价**当「原价」，菜单价照旧当「实付」。
            # 早期版本把 price 也换成结算价（四件套 28→57），结果榜单写 ¥66、
            # 点进购物车却是 ¥37，两边对不上（实测 3 行不一致）。
            # 会员价的披露交给 _row 里的 memberOnly + nonMemberPay —— 那套机制本来就有，
            # 页面上也一直显示「麦金卡 N 件 · 非会员需多付 X」。
            origin = sum((i.get("origin") or i["price"]) for i in its)
        else:
            origin = sum(i["price"] for i in its)
        now_price = sum(i["price"] for i in its)
        base_save = max(0.0, origin - now_price)
        save, cname = combo_coupon(its)
        note = " + ".join(i["name"] for i in items) + (f"，用「{cname}」" if cname else "")
        if settle and base_save > 0.009:
            note += f"；比单点省 ¥{base_save:.2f}"
        if settle and any(i.get("memberCut") for i in its):
            note += "（麦金卡商品按非会员结算价计）"
        row = _row(its, origin, base_save + save, cname, note, kind)
        all_rows.append(row)
        return row

    # 单独一个套餐就是一单（堡 + 薯条 + 饮料 [+ 派]），必须能被 ≤30 / ≤50 档选中：
    # 「麦香鸡套餐 28 元」比「单点一个堡 23.5 + 一杯可乐 9.5」更值，这才是用户想要的答案。
    for m in food:
        if m.get("setMeal"):
            add([m], "set", settle=True)

    # 单品：20 元档的答案常常就是「一个堡」，没有单品候选这档永远填不满
    for m in food:
        if not m.get("setMeal"):
            add([m], "single")

    # 主食 + 小食（20 元档主力：再加一杯饮料就 23.5 起了）
    cheap_sides = sorted(sides, key=lambda x: x["price"])[:6]
    for a in mains:
        for c in cheap_sides:
            if c["code"] != a["code"]:
                add([a, c], "combo")

    # 主食 + 饮品
    for a in mains:
        for b in drinks:
            if b["code"] != a["code"]:
                add([a, b], "combo")

    # 主食 + 饮品 + 小食（每个主食只配最便宜的 3×3，否则组合数上万）
    cheap_drinks = sorted(drinks, key=lambda x: x["price"])[:3]
    cheap3 = sorted(sides, key=lambda x: x["price"])[:3]
    for a in mains:
        for b in cheap_drinks:
            for c in cheap3:
                if len({a["code"], b["code"], c["code"]}) == 3:
                    add([a, b, c], "combo")

    # ---------- 100+：套餐优先的多人拼单 ----------
    # 旧版从单品池里拼 6 件（2 堡 + 2 饮 + 2 小食），结果报出
    # 「培根安格斯 + 芝士安格斯 + 可乐 + 美式 + 苹果片 + 派」——
    # 6 个全是单点，同预算买套餐能多一件还更便宜，用户一眼看出「这不是套餐」。
    #
    # 现在把**套餐当成原子单位**，只枚举三种结构：
    #   ① 2 个大套餐（四件套 / 双人餐 / 随心拼）—— 2 人份的标准解
    #   ② 1 个大套餐 + 1 个单品堡补齐
    #   ③ 3 个三件套 —— 用户原话「吃三件套买 3 个也比单点划算」，这一条必须能被选出来
    # 排序：套餐件数占比 → 预算贴近度（越接近 100 越好）→ 省额 → 热量。
    set_big = [m for m in food
               if re.search(r"四件套|双人餐|随心拼|拼盘|四宫格", m["name"])
               and not SAUCE_RE.search(m["name"])]
    set_mid = [m for m in food if "三件套" in m["name"]]
    plain_mains = [m for m in mains if not m.get("setMeal")]
    multi_cand = []
    for a, b in itertools.combinations(set_big, 2):
        if set_core(a["name"]) == set_core(b["name"]):
            continue
        multi_cand.append(([a, b], 2))
    for a in set_big:
        for b in sorted(plain_mains, key=lambda x: -settle_price(x))[:6]:
            multi_cand.append(([a, b], 1))
    for trio in itertools.combinations(set_mid, 3):
        if len({set_core(x["name"]) for x in trio}) < 3:
            continue
        multi_cand.append((list(trio), 3))

    multi_rows = []
    for items, sc_cnt in multi_cand:
        row = add(items, "multi", settle=True)
        # 100 块的档不该答成 200 块（2 份 BFF 双人餐），也不该答成 60 块
        if row["pay"] < 100 - 1e-9 or row["pay"] > 140:
            continue
        coverage = sc_cnt / max(1, len(row["items"]))
        multi_rows.append((round(coverage, 3), -abs(row["pay"] - 100), row["save"],
                           row["kcal"], sc_cnt, row))

    # 注意：这里原本有一段「N 元任选 M 件 → 直接按券凑一单」的逻辑，已删除。
    # 它按券名关键字从全菜单捞商品凑数，把券不管辖的商品也算进「任选」（虚报 16 元），
    # 现在这类券统一由 verified_coupon_rules() 按核价 SKU 出榜。

    # ---------- 预算分档：每档回答「这些钱怎么点最值」 ----------
    # 用户问的是「我有 20 / 30 / 50 / 100 块，怎么点最划算」，
    # 要回答的是「该档预算内最优的一单」，而不是把榜单筛一遍。
    #
    # 三条规则，缺一档就会答错：
    #   ① 预算要用足：只在 [cap×0.6, cap] 内挑。否则「我有 50 块」会被答成一份 14 元的鸡排。
    #   ② 必须是一顿饭：20 元内凑不出「主食+饮品」（最便宜 23.5），这一档只要求有主食；
    #      30/50 必须含饮品，否则会选出一杯咖啡当午饭。
    #   ③ 排序先比省下的钱、再比省的比例、最后比每元热量。
    #      不能先比每元热量：省 40% 的两件套（20.48 元）会被「热量待核」打成 0 分而落选，
    #      结果每档都退化成「现价买东西」，等于没帮你省钱。
    def has_code(r, codes):
        return any(i["code"] in codes for i in r["items"])

    def budget_key(r):
        return (r["save"], r["savePct"], r["perYuanKcal"], r["kcal"])

    budgets = []
    prev_pay = 0.0
    for cap in (20, 30, 50):
        cand = [r for r in all_rows if r["kind"] != "multi" and r["pay"] <= cap + 1e-9]
        # 递进：这一档必须比上一档多花钱（至少 20%），否则「我有 50 块」会被答成
        # 一个 30 元的单子 —— 上一档已经答过了，重复回答等于没回答。
        # 预算用足：只在 [cap×0.75, cap] 内挑。门槛低了会答成「我有 50 块，结果推荐一份 37 元
        # 的两件套」—— 省是省了 13 块，但这档预算根本没被用上，用户会觉得答非所问。
        # 20 元档例外放到 0.6：这一档预算本来就小，苛求用足反而会错过「14 元鸡排 385kcal」
        # 这种每元热量最高的答案，换成 17 元的汉堡。
        floor = max(cap * (0.6 if cap <= 20 else 0.7), prev_pay * 1.2)
        band = [r for r in cand if r["pay"] >= floor] or cand
        # 麦金卡价不能当「这钱怎么点」的答案：四件套菜单 28、非会员结算 57，
        # 「预算 30」档若答它，没开卡的人到结算页会直接超预算。
        # 所以先只用「人人可用」的价，实在没有（整档都是会员价商品）再退回带标记的方案。
        free_band = [r for r in band if not r.get("memberOnly")]
        if free_band:
            band = free_band
        # 30/50 档要求「主食 + 饮品」，否则会答成一杯咖啡当午饭。
        # 但套餐（三件套/套餐/四件套）的饮品在套餐里，数据层面没有拆出饮品 SKU，
        # 所以 kind="set" 直接视为「有饮品」—— 否则 30 元档会漏掉
        # 「大堡口福三件套 ¥22.9（省 24.1）」这种明显最优的答案。
        meal = [r for r in band
                if has_code(r, main_codes)
                and (cap < 30 or has_code(r, drink_codes) or r.get("kind") == "set")] or band
        if not meal:
            budgets.append({"cap": cap, "row": None, "count": 0})
            continue
        best = max(meal, key=budget_key)
        prev_pay = best["pay"]
        why = ("用券后省得最多" if best["save"] > 0 else "档内每元热量最高")
        if best.get("kcal") == 0:
            why += "（这单热量待核，不参与热量对比）"
        budgets.append({
            "cap": cap, "row": best, "count": len(cand),
            "need": "一份主食" if cap < 30 else "主食 + 饮品",
            "why": why,
        })

    # 100+：套餐优先的多人拼单（见上方 multi_rows 的构建说明）
    if multi_rows:
        multi_rows.sort(key=lambda t: (t[0], t[1], t[2], t[3]), reverse=True)
        coverage, _, _, _, sc_cnt, m100 = multi_rows[0]
        people = max(2, sc_cnt)
        all_sets = sc_cnt == len(m100["items"])
        budgets.append({
            "cap": 100, "row": m100, "count": len(multi_rows), "multi": True,
            "people": people, "setCount": sc_cnt, "allSets": all_sets,
            "coverage": round(coverage * 100),
            "need": f"{people} 人份 · {sc_cnt} 个套餐",
            "why": ("全套餐组合：同预算下比单点多吃一件，还便宜" if all_sets
                    else f"{sc_cnt} 个套餐 + 单品补齐，套餐占大头"),
        })

    # ---------- 展示列表 ----------
    # 列表要让「20 块 / 30 块 / 50 块」都看得到东西，不能二十几行全挤在 40 元上下。
    # 按价位分桶各取 6 条，同一主食不重复（避免整屏都是同一个堡）。
    # 「套餐最优」榜里必须是一顿饭：只含一杯咖啡的行不该出现在这里
    combo_rows = [r for r in all_rows
                  if r["kind"] != "multi"
                  and any(i["code"] in main_codes for i in r["items"])]
    picked, seen_main = [], set()
    for lo, hi in [(0, 25), (25, 35), (35, 50), (50, 1e9)]:
        n = 0
        for r in sorted([x for x in combo_rows if lo <= x["pay"] < hi],
                        key=lambda x: (x.get("memberOnly", False), -x["save"], -x["perYuanKcal"])):
            key = r["items"][0]["code"]
            if key in seen_main:
                continue
            seen_main.add(key)
            picked.append(r)
            n += 1
            if n >= 6:
                break
    combo_rows = picked

    # 券后最省：单项与组合混排，按省下的钱排
    coupon_rows = [r for r in coupon_rows if r["save"] > 0]
    coupon_rows.sort(key=lambda r: (-r["save"], -r["savePct"]))

    # ---------- 今日最优解：省得多、还得是一顿完整的饭 ----------
    # 只从「人人可用」的行里选：麦金卡会员价对非会员不成立，不能当今日最优解。
    # 必须在全量候选里挑（combo_rows 已被价位分桶，省最多那单可能不在里面），
    # 且必须含主食 —— 否则一张咖啡券省 9.1 元就能当「今日最优解」，不合常理。
    # 「今日最优解」是给一个人看的一单，所以加 55 元上限 ——
    # 不加上限时会被「堡堡随心拼（7 件任选）省 29 元」占住，72.5 元不像"今日最优"。
    public = [r for r in all_rows
              if r["kind"] != "multi" and r["save"] > 0 and not r.get("memberOnly")
              and r["pay"] <= 55 and has_code(r, main_codes)]
    public += [r for r in drop_rows
               if not r.get("memberOnly")
               and re.search(r"套餐|四件套|三件套|随心选", r["items"][0]["name"])]
    hero = None
    if public:
        hero = max(public, key=lambda r: (r["save"], r["savePct"]))
    elif combo_rows:
        hero = combo_rows[0]
    if hero:
        hero = dict(hero)
        hero["tip"] = (f"同样的东西原价 ¥{hero['origin']:.2f}，实付 ¥{hero['pay']:.2f}，"
                       f"省 {hero['save']:.2f} 元（{hero['savePct']}%）")
        if hero.get("memberOnly"):
            hero["tip"] += f"；这是麦金卡会员价，非会员实付 ¥{hero['nonMemberPay']:.2f}"

    coupon_basis = ("每张券都用 calculate-price 真实核价，按实际省下的钱排序；"
                    "核价不通过的券不上榜") if vrules else \
                   ("暂无核价结果，按券名估算（仅供排序参考，实付请以 calculate-price 为准）")

    # 官方直降：先给真正的公开直降，末尾最多补 2 条麦金卡会员价（带 🪪 标记），
    # 既不误导非会员，也不把「四件套 57→28」这种招牌价藏起来。
    drop_public = [r for r in drop_rows if not r.get("memberOnly")][:6]
    drop_member = [r for r in drop_rows if r.get("memberOnly")][:2]

    boards = [
        {"id": "coupon", "name": "券后最省", "icon": "🎟️",
         "desc": coupon_basis,
         "unit": "省", "rows": coupon_rows[:6]},
        {"id": "drop", "name": "官方直降", "icon": "🏷️",
         "desc": "MCP 返回的划线价对比，不用券也比原价便宜（末位标🪪的是麦金卡会员价，非会员按划线价结算）", "unit": "降",
         "rows": drop_public + drop_member},
        {"id": "combo", "name": "套餐最优", "icon": "🍱",
         "desc": "按预算分档给「这钱怎么点最值」：≤20 / ≤30 / ≤50 各一单，100 以上是多人拼单", "unit": "省",
         "rows": combo_rows[:24]},
        {"id": "kcal", "name": "每元管饱", "icon": "🍚",
         "desc": "每 1 元能换多少大卡，管饱优先", "unit": "kcal/元",
         "rows": kcal_rows[:6]},
        {"id": "protein", "name": "每元蛋白", "icon": "💪",
         "desc": "每 1 元能换多少蛋白质，健身向", "unit": "g/元",
         "rows": protein_rows[:6]},
    ]

    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "basis": ("price/origin/kcal/protein 全部来自 MCP 快照；"
                  "券后金额一律取 calculate-price 的 realDiscount（券只作用在它核价吃下的 SKU 上），"
                  "生成榜单前会按当前时间再复核一次券的有效期，过期/未生效的券不进榜"),
        "hero": hero,
        "budgets": budgets,
        "boards": boards,
    }


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
                    claimed_titles: set = None, codes_map: dict = None,
                    approx_map: dict = None) -> list:
    rems = []
    now = datetime.now()
    claimed_titles = claimed_titles or set()
    codes_map = codes_map or {}
    approx_map = approx_map or {}

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
            "codesApprox": bool(approx_map.get(c.get("name", ""))),
        })

    # 2) 可领取但尚未领取的券 —— 这是最容易错过的羊毛
    #    领取状态**只认 available-coupons 自己返回的状态**（含回退推断）。
    #    历史 bug：这里原来用「标题是否出现在卡包/门店券」判断，
    #    导致 already-claimed 的「免费脆薯饼」仍被当成「待领券」推送，自相矛盾。
    for a in available:
        title = a.get("title") or a.get("name") or ""
        if not title:
            continue
        if a.get("claimed") is None:
            if title in claimed_titles:
                continue
        elif a.get("claimed"):
            continue
        rems.append({
            "level": "warn", "icon": "🚨", "type": "待领券",
            "title": title, "desc": "当前可领取，尚未领取 —— 别错过",
            "deadline": "", "days": 0,
            "codes": a.get("codes") or codes_map.get(title, []),
            "codesApprox": bool(a.get("codesApprox") if a.get("codesApprox") is not None
                                else approx_map.get(title, False)),
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
    """解析 available-coupons。
       优先用结构化 JSON（含权威状态 couponStatus），文本仅作兜底。
       couponStatus: HAVING_RECEIVE=已领取 / 其余=未领取"""
    out = []
    try:
        j = extract_json(raw) or {}
        if isinstance(j, dict):
            j = j.get("data")
        for a in (j or []):
            if not isinstance(a, dict):
                continue
            title = str(a.get("couponName") or "")
            if not title:
                continue
            st = str(a.get("couponStatus") or "").upper()
            claimed = True if st == "HAVING_RECEIVE" else (False if st else None)
            out.append({
                "title": title,
                "claimed": claimed,
                "status": st,
                "label": str(a.get("label") or ""),
                "image": str(a.get("couponImage") or ""),
            })
        if out:
            return out
    except Exception:
        pass

    # ---- 兜底：文本解析 ----
    blocks = re.split(r"\n\s*-\s*优惠券标题：", raw)
    for b in blocks[1:]:
        lines = b.split("\n")
        title = lines[0].strip().rstrip("\\").strip()
        if not title:
            continue
        sm = re.search(r"状态：\s*(已领取|未领取)", b)
        st = sm.group(1) if sm else None
        out.append({"title": title, "status": "",
                    "claimed": (True if st == "已领取" else (False if st == "未领取" else None))})
    return out


def parse_my_coupons(raw: str) -> list:
    """解析 query-my-coupons（我的卡包）。
       结构化 JSON 里每个券都带 id / code / discountInfo / beTypes / orderTypes /
       tradeEndDate / totalAvailableCount —— 这些才是「能不能用、能省多少」的真字段，
       早期版本用 markdown 正则只抓了个名字，导致券无法试算、也无法回传给
       calculate-price，是「券信息与功能断裂」的根因。"""
    out = []
    try:
        j = extract_json(raw) or {}
        data = j.get("data") if isinstance(j, dict) else None
        arr = (data or {}).get("coupons") if isinstance(data, dict) else data
        for c in (arr or []):
            if not isinstance(c, dict):
                continue
            title = str(c.get("title") or c.get("couponName") or "")
            if not title:
                continue
            di = c.get("discountInfo") or {}
            tags = []
            for t in (c.get("tags") or []):
                if isinstance(t, dict):
                    tags.append(str(t.get("label") or t.get("value") or ""))
                else:
                    tags.append(str(t))
            tags = [t for t in tags if t]
            out.append({
                "name": title,
                "couponId": str(c.get("id") or ""),
                "couponCode": str(c.get("code") or ""),
                # discountValue 语义 = 用券后的价格（元），不是减免额
                "discountValue": to_float(di.get("discountValue")),
                "discountDesc": str(di.get("discountDesc") or ""),
                "discountTypeText": str(di.get("discountTypeText") or ""),
                "tradeEndDate": str(c.get("tradeEndDate") or ""),
                "tradeStartDate": str(c.get("tradeStartDate") or ""),
                "orderTypes": c.get("orderTypes") or [],
                "beTypes": c.get("beTypes") or [],
                "ifFreeCoupon": bool(c.get("ifFreeCoupon")),
                "appliedCategory": c.get("appliedCategory"),
                "totalCount": to_int(c.get("totalCount")),
                "totalAvailableCount": to_int(c.get("totalAvailableCount")),
                "tags": tags,
                "valid": (f"{c.get('tradeStartDate','')}~{c.get('tradeEndDate','')}"
                          if c.get("tradeEndDate") else ""),
                "inMine": True,
            })
        if out:
            return out
    except Exception:
        pass

    # ---- 兜底：markdown 文本 ----
    for m in re.finditer(r"^#+\s*(.+?)\s*$", raw, re.M):
        name = m.group(1).strip()
        if name.startswith("您的优惠券") or "共" in name:
            continue
        blk = raw[m.end(): m.end() + 400]
        dm = re.search(r"\*\*有效期\*\*[:：]\s*(.+)", blk)
        out.append({"name": name, "valid": (dm.group(1).strip() if dm else ""), "inMine": True})
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


def title_to_codes(title: str, menu_names: dict, direct_match) -> tuple:
    """券标题（如「9.9元中杯冰美式」「免费脆薯饼」）→ (菜单编码列表, 是否近似匹配)。

    三段式：
      1) 清洗后直接匹配（互相包含）→ exact=True
      2) 编码直配（menu_names 里的名字直接命中）
      3) 2-gram 相似度兜底 → exact=False，**只能用于「在菜单里定位」，不可用于金额抵扣**
         （历史 bug：「免费脆薯饼」被 2-gram 匹配到「心形薯饼5块」¥14.5，
          用户以为免费，结果按 14.5 计入应付。所以近似匹配必须打标记。）
    """
    key = title_key(title)
    if not key:
        return [], False
    out = direct_match(key)
    if out:
        return out[:4], False
    # 2-gram 滑窗兜底：「脆薯饼」→「心形薯饼5块」
    kb = {key[i:i + 2] for i in range(len(key) - 1)}
    if not kb:
        return [], False
    scored = []
    for code, name in menu_names.items():
        hit = sum(1 for g in kb if g in name)
        if hit:
            scored.append((hit / len(kb), code))
    scored.sort(reverse=True)
    return [c for s, c in scored if s >= 0.3][:4], True


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
# MCP Server 支持的 Tools 清单（页面右栏「MCP Tools」面板的数据源）
# =============================================================================
# 35 个工具全部是 tools/list 里真实存在、且在本项目里真实调用过的，
# 不是抄官方 README（`query-promotions`、`query-survey-coupon` 官方 README 没列，
# 但 server 里确实有）。参数名同样来自实测，照抄即可跑通。
#
# 页面把这份清单渲染成可折叠面板：单条复制 / 一键复制全部（Markdown）。
# 目的很直接 —— 任何人拿到这个页面，都能看到「我接的这套 MCP 到底能干什么、怎么调」。
MCP_TOOLS = {
    "server": "麦当劳 MCP Server（Streamable HTTP）",
    "count": 35,
    "updatedAt": "2026-10-24",
    "note": ("参数与示例均来自本项目真实调用。标 ⚠️ 的是写操作"
             "（会真实下单 / 领券 / 取消），执行前必须经过用户确认。"),
    "groups": [
        {"id": "store", "name": "门店与菜单", "icon": "🏪", "items": [
            {"name": "query-nearby-stores", "desc": "按城市 / 关键词查附近门店（到店自提、得来速）",
             "args": "beType(1 自提 / 5 得来速)、searchType(1 收藏 / 2 按位置)；可选 city、keyword",
             "example": 'query-nearby-stores({"beType":1,"searchType":2,"city":"深圳市","keyword":"科技园"})'},
            {"name": "query-meals", "desc": "拉取门店当前可售菜单（分类 + 餐品 code + 标签 + 价格）",
             "args": "storeCode、beType、orderType(1 到店 / 2 外送)",
             "example": 'query-meals({"storeCode":"1420762","beType":1,"orderType":1})'},
            {"name": "query-meal-detail", "desc": "查单个餐品 / 套餐的组成与可替换项（DIY 必需）",
             "args": "storeCode、code、beType、orderType",
             "example": 'query-meal-detail({"storeCode":"1420762","code":"9900000890","beType":1,"orderType":1})'},
            {"name": "query-meal-assistance", "desc": "查套餐可选配 / 加价换购项",
             "args": "storeCode、code、beType、orderType",
             "example": 'query-meal-assistance({"storeCode":"1420762","code":"9900000890","beType":1,"orderType":1})'},
            {"name": "list-nutrition-foods", "desc": "能量 / 蛋白质 / 脂肪 / 碳水 / 钠 / 钙（约 158 条）",
             "args": "无",
             "example": 'list-nutrition-foods({})'},
            {"name": "now-time-info", "desc": "服务器当前时间与门店营业状态（判断能不能下单）",
             "args": "无",
             "example": 'now-time-info({})'},
        ]},
        {"id": "coupon", "name": "优惠券", "icon": "🎟️", "items": [
            {"name": "auto-bind-coupons", "desc": "⚠️ 一键领取当前全部可领券（写操作）",
             "args": "无",
             "example": 'auto-bind-coupons({})'},
            {"name": "query-store-coupons", "desc": "查门店可用券，含真实适用 SKU（`products[].productCode`）",
             "args": "storeCode、beType、orderType",
             "example": 'query-store-coupons({"storeCode":"1420762","beType":1,"orderType":1})'},
            {"name": "query-my-coupons", "desc": "查账号卡包里的券（**不校验门店/渠道**）",
             "args": "可选 page(≤5)、pageSize(≤200)",
             "example": 'query-my-coupons({"page":1,"pageSize":200})'},
            {"name": "available-coupons", "desc": "可领券列表，带 couponStatus（HAVING_RECEIVE=已领）",
             "args": "无",
             "example": 'available-coupons({})'},
            {"name": "query-survey-coupon", "desc": "问卷券（填问卷可领）",
             "args": "无",
             "example": 'query-survey-coupon({})'},
        ]},
        {"id": "trade", "name": "核价与下单", "icon": "🧾", "items": [
            {"name": "calculate-price", "desc": "⚠️ 带券核价：商品金额 + 配送费 − 优惠 = 应付；返回 takeWayList",
             "args": "storeCode、beType、orderType、items[]{productCode,quantity,couponId?,couponCode?}",
             "example": 'calculate-price({"storeCode":"1420762","beType":1,"orderType":1,'
                        '"items":[{"productCode":"1406","quantity":1,'
                        '"couponId":"<couponId>","couponCode":"<couponCode>"}]})'},
            {"name": "create-order", "desc": "⚠️ 创建订单，返回订单详情与官方支付链接",
             "args": "storeCode、orderType、beType、items[]；takeWayCode 取自 calculate-price；"
                     "外送需 addressId；可选 needTableware、remark(≤50 字)",
             "example": 'create-order({"storeCode":"1420762","beType":1,"orderType":1,'
                        '"takeWayCode":"eat-in","items":[{"productCode":"1406","quantity":1}]})'},
            {"name": "query-order", "desc": "查单笔订单详情与状态",
             "args": "orderId",
             "example": 'query-order({"orderId":"<orderId>"})'},
            {"name": "order-list", "desc": "查历史订单列表",
             "args": "可选 page、pageSize",
             "example": 'order-list({"page":1,"pageSize":10})'},
            {"name": "cancel-order", "desc": "⚠️ 取消订单",
             "args": "orderId、cancelReasonCode(1 改主意 / 2 重复下单 / 3 点错 / 4 地址电话错 / 5 时间选错 / -1 其它)",
             "example": 'cancel-order({"orderId":"<orderId>","cancelReasonCode":1})'},
        ]},
        {"id": "delivery", "name": "外送（麦乐送）", "icon": "🛵", "items": [
            {"name": "delivery-query-addresses", "desc": "外送地址列表（只有地址，没有门店信息）",
             "args": "无",
             "example": 'delivery-query-addresses({})'},
            {"name": "delivery-query-stores", "desc": "按地址查可配送门店，返回 storeCode + **beCode** + 配送费/起送",
             "args": "addressId、beType(2 麦乐送 / 6 团餐)",
             "example": 'delivery-query-stores({"addressId":"<addressId>","beType":2})'},
            {"name": "delivery-create-address", "desc": "⚠️ 新建配送地址，返回 addressId",
             "args": "address、addressDetail、city、contactName、phone(11 位纯数字)；可选 gender",
             "example": 'delivery-create-address({"address":"深圳市南山区科技园","addressDetail":"1 栋 101",'
                        '"city":"深圳市","contactName":"张三","phone":"13800138000"})'},
        ]},
        {"id": "member", "name": "会员 · 积分 · 商城", "icon": "🎁", "items": [
            {"name": "query-my-account", "desc": "账号信息与积分余额",
             "args": "无",
             "example": 'query-my-account({})'},
            {"name": "mall-points-products", "desc": "积分商城商品列表（可按 catRuleIds 筛选）",
             "args": "可选 catRuleIds、page",
             "example": 'mall-points-products({"page":1})'},
            {"name": "mall-product-detail", "desc": "积分商品详情",
             "args": "productId",
             "example": 'mall-product-detail({"productId":"<productId>"})'},
            {"name": "mall-create-order", "desc": "⚠️ 积分兑换下单（shopId=2；多商品必须分别下单并排队）",
             "args": "shopId=2、productId、quantity",
             "example": 'mall-create-order({"shopId":2,"productId":"<productId>","quantity":1})'},
            {"name": "mall-order-list", "desc": "积分订单列表",
             "args": "可选 page、pageSize",
             "example": 'mall-order-list({"page":1})'},
            {"name": "mall-order-detail", "desc": "积分订单详情",
             "args": "orderId",
             "example": 'mall-order-detail({"orderId":"<orderId>"})'},
        ]},
        {"id": "campaign", "name": "活动 · 抽奖 · 团餐", "icon": "🎯", "items": [
            {"name": "query-promotions", "desc": "门店满减 / 满折规则（现用于团餐场景）",
             "args": "storeCode、beType(6)、orderType(2)",
             "example": 'query-promotions({"storeCode":"1420762","beType":6,"orderType":2})'},
            {"name": "campaign-calendar", "desc": "当月活动日历（1+1、随心配等）",
             "args": "可选 specifiedDate(yyyy-MM-dd)",
             "example": 'campaign-calendar({"specifiedDate":"2026-10-24"})'},
            {"name": "query-lottery-info", "desc": "抽奖活动信息与剩余次数",
             "args": "无",
             "example": 'query-lottery-info({})'},
            {"name": "draw-lottery", "desc": "⚠️ 抽奖（消耗次数，结果不可撤销）",
             "args": "无",
             "example": 'draw-lottery({})'},
            {"name": "query-my-prizes", "desc": "我的奖品与核销状态",
             "args": "无",
             "example": 'query-my-prizes({})'},
            {"name": "query-party-city", "desc": "团餐可下单城市",
             "args": "无",
             "example": 'query-party-city({})'},
            {"name": "query-party-store", "desc": "城市下的团餐门店",
             "args": "cityId",
             "example": 'query-party-store({"cityId":"<cityId>"})'},
            {"name": "query-party-store-date", "desc": "团餐门店可预约日期",
             "args": "storeCode",
             "example": 'query-party-store-date({"storeCode":"<storeCode>"})'},
            {"name": "query-party-store-session", "desc": "团餐门店可预约时段",
             "args": "storeCode、date",
             "example": 'query-party-store-session({"storeCode":"<storeCode>","date":"2026-10-26"})'},
            {"name": "party-order-create", "desc": "⚠️ 团餐下单（shopId=5）",
             "args": "shopId=5、storeCode、date、session、items[]、contactName、phone",
             "example": 'party-order-create({"shopId":5,"storeCode":"<storeCode>",'
                        '"date":"2026-10-26","session":"<session>"})'},
        ]},
    ],
}


# =============================================================================
# 主流程
# =============================================================================
def _load_cache() -> dict:
    path = os.path.join(ROOT, "assets", "data.js")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    body = raw[raw.index("window.MCD_REAL_DATA"):]
    body = body[body.index("=") + 1:].strip().rstrip(";")
    return json.loads(body)


# =============================================================================
# 对外脱敏：本仓库是公开仓库，快照里不允许留下任何「属于本机账号」的凭证
# =============================================================================
MASK = "****"


def _mask_tail(s, keep: int = 4) -> str:
    s = str(s or "")
    return (MASK + s[-keep:]) if len(s) > keep else MASK


def sanitize_snapshot(payload: dict) -> dict:
    """把公开快照里的个人凭证抹掉，其余字段（价格 / 券规则 / 核价结果）原样保留。

    - `account.accountId`：麦享会会员号 → 只留后 4 位（页面只展示积分，不依赖完整号）
    - `myCoupons[].couponId` / `couponCode`：卡包券的核销凭证 → 直接删除
      券名、面额、有效期、realOk / realDiscount / realPay 全部保留，
      页面展示与省钱榜单计算均不受影响（前端从不读取这两个字段）。
    - `coupons[].id` / `code`：门店公开券，任何持 Token 的用户查同一家店都会拿到同一份，
      不构成个人泄漏，保留以便使用者核价。

    幂等：重复调用不会继续截断已脱敏的值。
    """
    acc = payload.get("account")
    if isinstance(acc, dict):
        aid = acc.get("accountId")
        if aid and not str(aid).startswith(MASK):
            acc["accountId"] = _mask_tail(aid, 4)
    for c in (payload.get("myCoupons") or []):
        if isinstance(c, dict):
            c.pop("couponId", None)
            c.pop("couponCode", None)
    return payload


def _write_cache(payload: dict):
    sanitize_snapshot(payload)
    # 与上一份快照比对菜单条数：本次抓取若明显偏少（部分分类失败 / 已过营业时段），
    # 覆盖会让页面凭空少一半餐品。时段差异是正常现象，所以只告警不阻塞。
    try:
        prev = _load_cache()
        pm, nm = len(prev.get("menu") or []), len(payload.get("menu") or [])
        if pm >= 20 and nm < pm * 0.6:
            print(f"⚠️  菜单条数从 {pm} 降到 {nm}（<60%）：可能抓取不完整或当前是早餐/夜宵时段，"
                  f"已照常写入，需要完整菜单请换到正餐时段重跑。")
    except Exception:
        pass
    path = os.path.join(ROOT, "assets", "data.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write("/* 由 scripts/build_data.py 从麦当劳 MCP 真实返回生成，请勿手改 */\n")
        f.write("window.MCD_REAL_DATA = ")
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    return path


def rank_from_cache(also_scenes: bool = False):
    """离线重算省钱榜单：不做任何 MCP 调用，只用 assets/data.js 里已有的真实快照。

    价格 / 划线原价 / 热量 / 蛋白全部是 MCP 当时的返回值，只重新做组合与排序，
    不会新增任何编造数据。
    """
    payload = _load_cache()
    menu = payload.get("menu") or []
    # 先补套餐营养（只算主堡 → 加上薯条/可乐/派），场景筛选与榜单排序都吃这个值
    set_stats = enrich_set_nutrition(menu)
    print(f"      套餐营养: 共 {set_stats['sets']} 个套餐，"
          f"补全 {set_stats['estimated']} / 官方整份 {set_stats['official']} / "
          f"构成不明 {set_stats['partial']} / 无数据 {set_stats['unknown']}")
    if also_scenes:
        for m in menu:
            m["scenes"] = classify_scenes(m)
        payload["scenes"] = build_scene_bundles(menu)
        payload["scenesRebuiltAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["savings"] = build_savings(menu, payload.get("coupons") or [])
    payload["tools"] = MCP_TOOLS
    path = _write_cache(payload)

    print(f"已离线重算省钱榜单并写回: {path}")
    sv = payload["savings"]
    hero = sv.get("hero")
    if hero:
        print(f"      今日最优解: {' + '.join(i['name'] for i in hero['items'])}"
              f" → 原价 ¥{hero['origin']} / 券后 ¥{hero['pay']} / 省 ¥{hero['save']}")
    for b in sv["boards"]:
        print(f"      {b['icon']} {b['name']}: {len(b['rows'])} 条")
        for i, r in enumerate(b["rows"][:3], 1):
            names = " + ".join(x["name"] for x in r["items"])
            print(f"          {i}. {names} ¥{r['pay']} (省 {r['save']}, {r['perYuanKcal']} kcal/元)")


def repick_from_cache():
    """离线重算场景组合：不做任何 MCP 调用，只用 assets/data.js 里已有的真实快照。

    用途：调整 build_scene_bundles 的挑选规则后，无需重新联网也能让快照与规则一致
    （餐品、价格、热量仍然是 MCP 当时返回的原值，不新增任何编造数据）。
    """
    payload = _load_cache()
    menu = payload.get("menu") or []
    enrich_set_nutrition(menu)
    for m in menu:
        m["scenes"] = classify_scenes(m)
    payload["scenes"] = build_scene_bundles(menu)
    payload["scenesRebuiltAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["scenesRebuildNote"] = "离线重算：数据仍为原快照，仅按新规则重选组合"
    payload["tools"] = MCP_TOOLS
    _write_cache(payload)

    print(f"已离线重算场景组合并写回: {os.path.join(ROOT, 'assets', 'data.js')}")
    for s in payload["scenes"]:
        sc_pool = {m["code"] for m in menu if s["id"] in (m.get("scenes") or [])}
        outside = 0
        for b in s.get("bundles") or []:
            for it in b["items"]:
                if it["code"] not in sc_pool:
                    outside += 1
        tag = "兜底" if s.get("fallback") else "命中"
        print(f"      {s['icon']} {s['name']}: {s['count']} 品 / {len(s['bundles'])} 组合"
              f" [{tag}] 跨场景商品 {outside} 件")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="深圳市")
    ap.add_argument("--keyword", default="科技园")
    ap.add_argument("--store-code", default="")
    ap.add_argument("--store-name", default="")
    ap.add_argument("--claim", action="store_true",
                    help="先调用 auto-bind-coupons 一键领取全部可领券（写操作，需用户同意）")
    ap.add_argument("--repick", action="store_true",
                    help="离线重算场景组合（不联网，只用现有 assets/data.js 快照）")
    ap.add_argument("--rank", action="store_true",
                    help="离线重算省钱榜单（不联网，只用现有 assets/data.js 快照）")
    args = ap.parse_args()

    if args.rank:
        rank_from_cache(also_scenes=args.repick)
        return

    if args.repick:
        repick_from_cache()
        return

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
            row = {
                "id": str(st.get("storeCode", "")),
                "name": st.get("storeName", ""),
                "addr": st.get("address", ""),
                "dist": round((st.get("distance") or 0) / 1000, 2),
                "hours": f"{st.get('businessStartTime','')}-{st.get('businessEndTime','')}",
                "open": bool(st.get("businessStatus")),
                "lat": st.get("latitude") or 0,
                "lng": st.get("longitude") or 0,
            }
            # 配送费 / 起送门槛 / 免配送门槛：门店接口若返回就带上，不返回就不写。
            # 前端只认这些真实字段，缺字段时不计配送费（并在界面标注「以结算页为准」），
            # 绝不硬编码一个「6 元」让用户误以为那就是最终要付的钱。
            fee = pick_num(st, ("deliveryFee", "shippingFee", "deliveryPrice", "freight"))
            mino = pick_num(st, ("minOrderPrice", "minPrice", "startPrice", "minOrder"))
            freeo = pick_num(st, ("freeDeliveryPrice", "freeShippingPrice", "freeFeeOver"))
            if fee is not None and fee > 0:
                row["fee"] = fee
            if mino is not None and mino > 0:
                row["min"] = mino
            if freeo is not None and freeo > 0:
                row["freeOver"] = freeo
            stores_out.append(row)
        if not stores_out:
            raise SystemExit("未查询到附近门店，请更换城市或关键词")
        store_code, store_name = stores_out[0]["id"], stores_out[0]["name"]
        n_fee = sum(1 for s in stores_out if "fee" in s)
        print(f"[1/6] 门店配送字段: {n_fee}/{len(stores_out)} 家返回了配送费"
              f"（未返回的按「以结算页为准」处理，不臆造）")
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
        apply_to, matched_by_name, skus = [], [], []
        for p in products:
            pc = str(p.get("productCode") or "")
            pname = str(p.get("productName") or "")
            if pc:
                skus.append({"code": pc, "name": pname})
            if pc and pc in menu_codes:
                apply_to.append(pc)
            else:
                # 编码不在菜单中 → 名称回退匹配（仅用于定位，不用于计价）
                for mc in match_menu_codes(pname):
                    if mc not in apply_to:
                        matched_by_name.append(mc)
        apply_to += [mc for mc in matched_by_name if mc not in apply_to]
        # 券自带 SKU：这是「这张券到底该买什么」的权威答案。
        # 实测「19.9 元王牌炸鸡任选 2」的 couponId 对应独立 SKU 9900016534
        # （核价 23.8 → 19.9，真实只省 3.9），而该 SKU 不在 query-meals 的菜单里。
        # 只按标题猜商品会把券算错，也会让用户在页面上根本点不到这张券。
        coupons_out.append({
            "id": str(c.get("couponId") or ""),
            "code": str(c.get("couponCode") or ""),
            "name": c.get("title") or "",
            "desc": "、".join([str(p.get("productName")) for p in products]) or "全场通用",
            "applyTo": apply_to,
            "skus": skus,
            "promotionId": str(c.get("promotionId") or ""),
            "valid": c.get("tradeDateTime") or "",
            "codeMatched": len(matched_by_name) == 0 and bool(apply_to),
        })
    print(f"[3/6] 门店可用券: {len(coupons_out)} 张"
          f"（编码直配 {sum(1 for c in coupons_out if c['codeMatched'])}，"
          f"名称回退 {sum(1 for c in coupons_out if not c['codeMatched'] and c['applyTo'])}，"
          f"自带 SKU {sum(len(c['skus']) for c in coupons_out)} 个）")

    # ---- 3a. 逐张券跑真实核价（这是唯一能确认「券到底能不能用、能省多少」的方式）----
    # 只看标题必然出错：实测「新人专享-中杯美式7折」对美式返回 600012
    # 「促销规则不支持该商品」，「人气麦旋风买一送一」返回「当前优惠券不可用」。
    # 这里把 calculate-price 的真实结果写进数据，页面直接展示，不再靠估算。
    for c in coupons_out:
        cid, ccode = c.get("id"), c.get("code")
        skus = c.get("skus") or []
        c["realOk"] = None
        c["realDiscount"] = None
        c["realPay"] = None
        c["realOrig"] = None
        c["realMsg"] = ""
        if not (cid and ccode and skus):
            continue
        sku = skus[0]
        try:
            cp = mcp_call_obj("calculate-price", {
                "storeCode": store_code, "orderType": 1, "beType": 1,
                "items": [{"productCode": sku["code"], "quantity": 1,
                           "couponId": cid, "couponCode": ccode}],
            }, token)
        except Exception as e:
            c["realMsg"] = f"核价异常: {e}"
            continue
        if not cp.get("success"):
            c["realOk"] = False
            c["realMsg"] = str(cp.get("message") or "核价失败")
            continue
        d = cp.get("data") or {}
        c["realOk"] = True
        c["realDiscount"] = round(to_float(d.get("discount")) / 100.0, 2)
        c["realPay"] = round(to_float(d.get("price")) / 100.0, 2)
        c["realOrig"] = round(to_float(d.get("productOriginalPrice")) / 100.0, 2)

    ok_n = sum(1 for c in coupons_out if c.get("realOk") is True)
    fail_n = sum(1 for c in coupons_out if c.get("realOk") is False)
    print(f"[3a] 真实核价: {ok_n} 张可用 / {fail_n} 张不可用"
          + ("（" + "；".join(f"{c['name']}→{c['realMsg']}"
                             for c in coupons_out if c.get("realOk") is False)[:120] + "）"
             if fail_n else ""))

    # ---- 3b. 营养 ----
    raw_n = mcp_call("list-nutrition-foods", {}, token)
    nutri = parse_nutrition(raw_n)
    print(f"[4/6] 营养: {len(nutri)} 条")

    # ---- 5. 提醒数据源 ----
    raw_m = json.dumps(mcp_call_obj("query-my-coupons", {"page": "1", "pageSize": "200"}, token),
                       ensure_ascii=False)
    my_coupons = parse_my_coupons(raw_m)

    available = parse_available(json.dumps(
        mcp_call_obj("available-coupons", {}, token), ensure_ascii=False))

    # 已领取判定：优先用 available-coupons 自带的「状态」字段；
    # 接口未给状态时，回退为「标题出现在 卡包券 或 门店券 中」
    known_titles = {c.get("name", "") for c in my_coupons} | {c.get("title", "") for c in cdata}
    claimed_cnt = 0
    for a in available:
        if a.get("claimed") is None:
            a["claimed"] = (a.get("title") or "") in known_titles
        claimed_cnt += bool(a["claimed"])

    # ---- 卡包券的真实核价结果 ----
    # query-my-coupons 不返回适用商品，所以用同标题的门店券核价结果回填；
    # 匹配不上的（如「人气麦旋风买一送一」beTypes=[4]、「新人 7 折」）标记为
    # 「未验证」，页面据此显示「需在结算页核销」，绝不假装能省。
    real_by_title = {c.get("name", ""): c for c in coupons_out}
    for m in my_coupons:
        src = real_by_title.get(m.get("name", ""))
        if src and src.get("realOk") is not None:
            m["realOk"] = src.get("realOk")
            m["realDiscount"] = src.get("realDiscount")
            m["realPay"] = src.get("realPay")
            m["realOrig"] = src.get("realOrig")
            m["realMsg"] = src.get("realMsg", "")
            m["skus"] = src.get("skus")
        else:
            m["realOk"] = None
            m["realDiscount"] = None
            m["realPay"] = None
            m["realOrig"] = None
            m["realMsg"] = "未能在门店券里找到适用商品，需在结算页核销"
            m["skus"] = []
    n_verified = sum(1 for m in my_coupons if m.get("realOk") is not None)
    print(f"[5a] 卡包券核价: {n_verified}/{len(my_coupons)} 张已验证"
          + (f"，{len(my_coupons) - n_verified} 张需结算页核销" if len(my_coupons) > n_verified else ""))

    # 提醒点击 → 菜单选品映射（券标题 → 菜单编码）。
    # 优先级必须是：券自带 SKU > 门店券 applyTo > 标题精确匹配 > 2-gram 近似匹配。
    # 实测「19.9 元王牌炸鸡任选 2」靠标题会匹到 9900016077，而券真实 SKU 是
    # 9900016534 —— 用错 SKU 会让用户点了券却买错东西，甚至算错钱。
    codes_map, approx_map = {}, {}
    skus_by_title = {c.get("name", ""): [s["code"] for s in (c.get("skus") or [])]
                     for c in coupons_out}
    apply_by_title = {c.get("name", ""): (c.get("applyTo") or []) for c in coupons_out}

    def resolve_codes(title: str):
        """返回 (codes, approx)。只在「券自带 SKU / applyTo」都用不上时才猜。"""
        skus = [s for s in skus_by_title.get(title, []) if s]
        if skus:
            return skus, False
        ap = [s for s in apply_by_title.get(title, []) if s]
        if ap:
            return ap, False
        return title_to_codes(title, menu_names, match_menu_codes)

    for a in available:
        t = a.get("title") or ""
        c, approx = resolve_codes(t)
        codes_map[t] = c
        approx_map[t] = approx
        a["codes"] = c
        a["codesApprox"] = approx
    for c in coupons_out:
        name = c["name"]
        cc, approx = resolve_codes(name)
        codes_map[name] = cc
        approx_map[name] = approx

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
            raw_tags = m.get("tags") or []
            flat_tags = [str(t) for t in raw_tags]
            # 关键：菜单 currentPrice 有两种口径
            #   ① 普通商品 = 直接购买价（calculate-price 的 productPrice 与之一致）
            #   ② 带「麦金卡」标签的商品 = 付费会员卡价；没有该权益的账号核价会按
            #      originalPrice 收（实测 28 → 57、62.9 → 122.5），必须单独标记，
            #      否则页面显示的应付金额会低于真实结算价，属于「算错钱」。
            is_member_price = any("麦金卡" in t for t in flat_tags)
            item = {
                "code": code, "name": name, "cat": cname,
                "price": to_float(d.get("currentPrice")),
                "origin": to_float(d.get("originalPrice")),
                "memberPrice": is_member_price,
                "kcal": to_int(n.get("energyKcal")),
                "kcalEstimated": bool(n.get("kcalEstimated")),
                "protein": round(to_float(n.get("protein")), 1),
                "fat": round(to_float(n.get("fat")), 1),
                "carb": round(to_float(n.get("carb")), 1),
                "sodium": to_int(n.get("sodium")),
                "image": d.get("image") or "",
                "tags": raw_tags,
                "discountType": d.get("discountType"),
            }
            item["scenes"] = classify_scenes(item)
            menu_out.append(item)

    # 空菜单守卫：非营业时间 query-meals 会返回 600057「门店可能已关闭或不在营业时间」，
    # 菜单 0 条。旧版本不看这个直接写文件，会把上一份完整快照覆盖成空菜单
    # （2026-10-25 00:02 实测踩到，112 餐品被刷成 0 条）。宁可报错退出，也不能写坏文件。
    if not menu_out:
        raise SystemExit("菜单为 0 条（门店可能未营业 / 接口异常），已中止写入，assets/data.js 保持原样")

    # 套餐营养补全必须在「打场景标签」与「生成场景组合」之前：
    # 官方只给主堡的热量（板烧四件套 391 == 板烧单品 391），不补配餐的话
    # 场景排序会把 1059 kcal 的四件套当成 391 kcal 的高蛋白餐。
    set_stats = enrich_set_nutrition(menu_out)
    print(f"[6a] 套餐营养: {set_stats['sets']} 个套餐，补全 {set_stats['estimated']} / "
          f"官方整份 {set_stats['official']} / 构成不明 {set_stats['partial']} / "
          f"无数据 {set_stats['unknown']}")

    # 场景化：给每个餐品打标签，并为每个场景生成推荐组合
    for m in menu_out:
        m["scenes"] = classify_scenes(m)

    # ---- 6b. 把「券专属 SKU」补进菜单 ----
    # 有些券只对独立 SKU 生效（如「19.9 元王牌炸鸡任选 2」→ 9900016534），
    # 这类 SKU 不在 query-meals 里。若不补进菜单，用户在页面上点不到这张券，
    # 就会出现「券显示可用、但没有东西可买」的功能断裂。
    coupon_only = []
    for c in coupons_out:
        for sku in (c.get("skus") or []):
            code = str(sku.get("code") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            cname = "券专属商品"
            n = match_nutrition(str(sku.get("name") or ""), nutri) or {}
            # 这类 SKU 不在 query-meals 里，单独核价会返回全 0 / productList 为空
            #（它只能配合对应券购买），所以用「带券核价」拿到的券前价当 price。
            base_price = to_float(c.get("realOrig")) or 0.0
            base_origin = base_price
            item = {
                "code": code, "name": str(sku.get("name") or code), "cat": cname,
                "price": base_price or 0.0,
                "origin": base_origin or base_price or 0.0,
                "memberPrice": False,
                "couponOnly": True,
                "kcal": to_int(n.get("energyKcal")),
                "kcalEstimated": bool(n.get("kcalEstimated")),
                "protein": round(to_float(n.get("protein")), 1),
                "fat": round(to_float(n.get("fat")), 1),
                "carb": round(to_float(n.get("carb")), 1),
                "sodium": to_int(n.get("sodium")),
                "image": "", "tags": ["券专属"], "discountType": None,
            }
            item["scenes"] = classify_scenes(item)
            menu_out.append(item)
            coupon_only.append({"code": code, "coupon": c.get("name", ""),
                                "price": base_price})

    if coupon_only:
        print(f"[6b] 补入券专属 SKU {len(coupon_only)} 个: "
              + "、".join(f"{x['code']}({x['coupon']} ¥{x['price']})" for x in coupon_only[:4]))

    scenes_out = build_scene_bundles(menu_out)

    matched = sum(1 for m in menu_out if m["kcal"] > 0)
    print(f"[6/6] 组装完成: {len(menu_out)} 餐品 / {matched} 条营养匹配")
    for s in scenes_out:
        tag = "兜底" if s.get("fallback") else "命中"
        print(f"      {s['icon']} {s['name']}: {s['count']} 品 / {len(s['bundles'])} 组合 [{tag}]")

    # 外送链路：delivery-query-stores 必须带 addressId，所以先看账号有没有收货地址。
    # 没有地址 → deliveryStores=[]，页面提示「先填收货地址」；
    # 有地址 → 把可配送门店连同 beCode / 配送费 / 起送门槛一起抓下来。
    # 这一步以前完全没做，导致 data.js 里没有外送 beCode，页面只能永远写
    # 「配送费以结算页为准」—— 不是接口不给，是我们从来没问。
    delivery_addr_count = 0
    delivery_stores = []
    try:
        ad = mcp_call_obj("delivery-query-addresses", {}, token)
        addrs = ((ad.get("data") or {}).get("addresses")) or []
        delivery_addr_count = len(addrs)
        addr_id = (addrs[0].get("addressId") if addrs else None)
        if addr_id:
            ds = mcp_call_obj("delivery-query-stores", {"beType": 2, "addressId": addr_id}, token)
            d = ds.get("data") or {}
            raw_ds = (d.get("stores") or d.get("storeList")
                      or d.get("storeInfos") or d.get("list") or [])
            for st in raw_ds[:12]:
                if not isinstance(st, dict):
                    continue
                sid = str(st.get("storeCode") or st.get("code") or st.get("storeId") or "")
                if not sid:
                    continue
                dist = pick_num(st, ("distance", "dist", "distanceValue"))
                if dist is not None and dist > 50:   # 接口单位可能是米
                    dist = round(dist / 1000, 2)
                delivery_stores.append({
                    "id": sid,
                    "name": st.get("storeName") or st.get("name") or "麦当劳外送门店",
                    "addr": st.get("address") or st.get("storeAddress") or "",
                    "dist": dist if dist is not None else 0,
                    "hours": st.get("businessTime") or st.get("openTime") or "",
                    "open": st.get("isOpen", True) is not False,
                    "beCode": str(st.get("beCode") or ""),
                    "fee": pick_num(st, ("deliveryFee", "shippingFee", "deliveryPrice", "fee")),
                    "min": pick_num(st, ("minOrderPrice", "minOrder", "startPrice", "min")),
                    "freeOver": pick_num(st, ("freeDeliveryPrice", "freeShippingPrice",
                                              "freeFeeOver", "freeOver")),
                })
    except Exception as e:
        print(f"[6c] 外送门店抓取跳过：{e}")
    print(f"[6c] 外送地址 {delivery_addr_count} 个 / 可配送门店 {len(delivery_stores)} 家"
          + ("" if delivery_addr_count
             else "（没填地址：先在页面填收货地址，再重跑本脚本即可拉到外送门店与真实配送费）"))

    # 省钱榜单 / MCP 工具清单必须由联网流程一并产出。
    # 旧版本只在 --rank / --repick 里写这两个字段，导致「按文档跑一次 build_data.py」
    # 得到的 data.js 没有榜单也没有 Tools 面板 —— 页面最关键的两块直接空白。
    savings_out = build_savings(menu_out, coupons_out)

    payload = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "store": {"code": store_code, "name": store_name},
        "stores": stores_out,
        "deliveryAddressCount": delivery_addr_count,
        "deliveryStores": delivery_stores,
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
        "scenesRebuiltAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reminders": build_reminders(my_coupons, available, account, lottery, prizes, campaigns,
                                     claimed_titles=known_titles, codes_map=codes_map,
                                     approx_map=approx_map),
        "savings": savings_out,
        "tools": MCP_TOOLS,
    }

    out = _write_cache(payload)
    hero = savings_out.get("hero") or {}
    if hero:
        print("[6d] 今日最优解: " + " + ".join(i["name"] for i in hero["items"])
              + f" → 原价 ¥{hero['origin']} / 实付 ¥{hero['pay']} / 省 ¥{hero['save']}")
    for b in savings_out.get("budgets") or []:
        r = b["row"]
        print(f"      ≤¥{b['cap']} → ¥{r['pay']}（省 ¥{r['save']}）"
              + " + ".join(i["name"] for i in r["items"]))
    print(f"已写入: {out}")


if __name__ == "__main__":
    main()
