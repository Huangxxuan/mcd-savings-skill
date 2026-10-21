# 参赛提交状态与操作手册

> 关键时间点：**2026-10-25 23:59 报名截止** ｜ **2026-10-26 00:00 定榜**
> 排名规则：纯按 GitHub 公开 **Star 数**（无评委评审，前 100 名进榜，Star=0 不进榜）

---

## 一、当前状态（2026-10-21 核对）

| 项 | 状态 | 详情 |
|---|---|---|
| 仓库 | ✅ 已上线 | <https://github.com/Huangxxuan/mcd-savings-skill>（Public / main，创建于 2026-10-20T14:12Z） |
| 推送 | ✅ 完成 | 本地与远端已同步，14 个文件，工作区干净 |
| 报名 Issue #932 | ❌ **审核未通过** | 官方机器人 2026-10-20T14:59Z 回复：「缺少 README.md/参赛申明/MCP说明」——**原因：机器人检查时首次推送尚未完成，仓库还是空的** |
| 必需文件 | ✅ 齐全 | `README.md` / `CONTEST_DECLARATION.md`（与官方原文逐字节一致，1522 B）/ `MCP_INTEGRATION.md` / 源代码 / `workbuddy.md` |
| 敏感信息 | ✅ 无 | 仅 `mcp-config.example.json` 内 `${MCD_MCP_TOKEN}` 占位符 |
| 仓库 Description / Topics | 🟡 部分 | Description 已填；Topics 待确认 |
| 演示 GIF | ⬜ 待录 | 见第三节，README 首屏用 |
| **重新报名** | ⬜ **待办（最紧急）** | 文件现已齐全，需**重新提交一个新 Issue**，见第二节 |

---

## 二、重新报名（最紧急，先做这个）

> 官方规则原文：「如果因不满足条件导致报名失败，系统也会在报名 Issue 下回复失败原因。完成相应修改后，你可以**重新提交 Issue**。」
> #932 已作废，**不要再在 #932 下回复**，直接新建一个 Issue。

**Issue Title：**
```
【参赛申请】麦麦省钱点单助手
```

**Issue Body（4 行，行内不换行，地址裸写）：**
```
【参赛申请】
项目名称：麦麦省钱点单助手
项目地址：https://github.com/Huangxxuan/mcd-savings-skill
项目简介：会算账的麦当劳点单专家，用真实价格和优惠券算出省钱榜单最优解，一键领券 + 自动用最优券 + 卡路里可视 + 五大场景搭配 + 拼单凑单 + 门店导航，把 MCP 真实数据渲染成可点击的点单助手
```

新建入口：<https://github.com/M-China/mcd-developer-innovation-challenge/issues/new>

**提交前 30 秒自检**（缺一不可）：

```bash
for f in README.md CONTEST_DECLARATION.md MCP_INTEGRATION.md workbuddy.md; do
  printf "%s  " "$(curl -s -o /dev/null -w '%{http_code}' https://raw.githubusercontent.com/Huangxxuan/mcd-savings-skill/main/$f)"
  echo "$f"
done
# 期望全部 200
```

---

## 三、日常更新流程（改完代码后推送）

```bash
cd /Users/huang/WorkBuddy/2026-10-20-17-09-03/mcd-savings-skill

# 1. 先看改了什么
git status --porcelain

# 2. 敏感信息扫描（必做，任一命中就停下）
grep -rInE "Bearer [A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{20,}" . 2>/dev/null \
  | grep -v "example.json" || echo "✅ 无敏感信息"

# 3. 提交并推送（远端有新提交时先 rebase）
git add -A
git commit -m "docs: 更新说明"
git pull --rebase origin main
git push origin main

# 4. 核对本地与远端一致
git fetch origin && git rev-parse HEAD origin/main
```

也可以直接用一键脚本（内含密钥扫描，命中会中止）：

```bash
cd /Users/huang/WorkBuddy/2026-10-20-17-09-03/mcd-savings-skill
./scripts/push_to_github.sh
```

> ⚠️ 认证：用户名 `Huangxxuan`，密码填 **Personal Access Token**（GitHub 已不支持账户密码推送）。
> Token 生成：<https://github.com/settings/tokens> → Generate new token (classic) → 勾 `repo`。
> **Token 一旦出现在截图/聊天/提交记录里，立刻吊销重建。**

---

## 四、还差的两步（提升 Star 转化率）

### 1. 仓库 Description 与 Topics

**Description：**
```
🍔 基于麦当劳中国 MCP 的可交互可视化点单 Skill：省钱榜单 · 一键领券 · 自动用最优券 · 卡路里可视 · 五大场景搭配 · 拼单凑单
```

**Topics（空格分隔，逐个回车录入）：**
```
mcdonalds mcp model-context-protocol workbuddy skill 1024 m-code ai-agent visualization ordering
```

### 2. 演示 GIF

录一段 30 秒内、能一眼看懂价值的动线：

> 点「办公下午茶」场景 → 弹出推荐方案 → 应用方案（菜单自动高亮） → 底部立省数字跳动 → 点「省钱榜单」→ 一键应用最优解 → 翻转祝福卡

存为 `assets/demo.gif`，README 首屏已留位置：

```html
<p align="center">
  <img src="./assets/demo.gif" width="820" alt="麦麦省钱点单助手演示">
</p>
```

> 建议 820px 宽、≤5 MB（GitHub 大图加载慢会掉星）。

---

## 五、报名 Issue 存档（#932 已作废，仅作记录）

**Title：**
```
【参赛申请】麦麦省钱点单助手
```

**Body（四行、每行不换行、地址裸写不用 Markdown 链接）：**
```
【参赛申请】
项目名称：麦麦省钱点单助手
项目地址：https://github.com/Huangxxuan/mcd-savings-skill
项目简介：会算账的麦当劳点单专家，省钱榜单找最优解 + 一键领券 + 自动用最优券 + 卡路里可视 + 场景搭配 + 拼单凑单 + 门店导航，把 MCP 真实数据渲染成可点击的点单助手
```

---

## 六、终审检查清单（10-25 当天跑一遍）

| # | 检查项 | 命令/方式 | 期望 |
|---|---|---|---|
| 1 | 仓库仍为 Public | GitHub 页面右上角 | ✅ Public |
| 2 | 无 Token 明文 | `git grep -nE "Bearer [A-Za-z0-9]{10,}"` | 无结果 |
| 3 | `mcp-config.example.json` 仅占位符 | `cat mcp-config.example.json` | 只有 `${MCD_MCP_TOKEN}` |
| 4 | `CONTEST_DECLARATION.md` 原样未改 | 与官方文件对比 | 完全一致 |
| 5 | `workbuddy.md` 存在且地址真实 | 打开文件 | 专项奖必需 ✅ |
| 6 | 页面可独立打开 | 双击 `assets/order-assistant.html` | 正常渲染、无 JS 报错 |
| 7 | 报名 Issue 已通过审核 | 新 Issue 下有官方「报名成功」回复 | ✅ 有回复即为成功；失败会写原因 |
| 8 | 无残留占位符 | `grep -rn "你的GitHub用户名" .` | 无结果 |

### 一键自检

```bash
cd /Users/huang/WorkBuddy/2026-10-20-17-09-03/mcd-savings-skill

echo "--- 1. 敏感信息 ---"
grep -rInE "Bearer [A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{20,}" . 2>/dev/null \
  | grep -v "example.json" || echo "✅ 安全"

echo "--- 2. 必需文件 ---"
for f in README.md CONTEST_DECLARATION.md MCP_INTEGRATION.md mcp-config.example.json SKILL.md workbuddy.md; do
  [ -f "$f" ] && echo "✅ $f" || echo "❌ 缺失 $f"
done

echo "--- 3. 占位符 ---"
grep -rn "你的GitHub用户名" README.md workbuddy.md SKILL.md 2>/dev/null || echo "✅ 无残留占位符"

echo "--- 4. 语法 ---"
node --check assets/order-assistant.html 2>/dev/null || echo "（HTML 跳过，用浏览器控制台验证）"
```
