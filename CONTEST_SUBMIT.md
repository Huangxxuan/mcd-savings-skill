# 参赛提交状态与操作手册

> 关键时间点：**2026-10-25 23:59 报名截止** ｜ **2026-10-26 00:00 定榜**
> 排名规则：纯按 GitHub 公开 **Star 数**（无评委评审，前 100 名进榜，Star=0 不进榜）

---

## 一、当前状态（2026-10-21 13:20 核对）

| 项 | 状态 | 详情 |
|---|---|---|
| 仓库 | ✅ 已上线 | <https://github.com/Huangxxuan/mcd-savings-skill>（Public / main，创建于 2026-10-20T14:12Z） |
| 推送 | ✅ 完成 | 本地 HEAD == 远端 `39858eb`；12 个文本/代码文件**字节级一致**；工作区干净 |
| **报名审核** | ✅ **已通过** | [Issue #936](https://github.com/M-China/mcd-developer-innovation-challenge/issues/936)，官方 2026-10-20 23:59 回复「您的作品已成功参赛」 |
| 必需文件 | ✅ 齐全 | `README.md` / `CONTEST_DECLARATION.md`（与官方原文逐字节一致，1522 B）/ `MCP_INTEGRATION.md` / 源代码 / `workbuddy.md` |
| 敏感信息 | ✅ 无 | 仅 `mcp-config.example.json` 内 `${MCD_MCP_TOKEN}` 占位符 |
| 仓库 Description | ✅ 已填 | 含省钱榜单等卖点 |
| 仓库 Topics | ⬜ **未设置** | 影响搜索曝光，5 分钟可补 |
| 演示 GIF | ⬜ 待录 | README 首屏用，今天必做 |
| **进榜距离** | ⚠️ **4 / 23 Star** | 2026-10-21 13:00 榜单：第 100 名门槛 **23 Star**，还差 **19 颗** |

> ℹ️ #932 因「首次推送晚于机器人检查」被判缺文件，已作废；#936 是有效报名。

---

## 二、报名记录（已通过，无需再提交）

> ✅ **有效报名：[Issue #936](https://github.com/M-China/mcd-developer-innovation-challenge/issues/936)**
> 官方 `M-China-Official` 于 2026-10-20 23:59 回复：「您的作品已成功参赛，您可以通过官方项目的排行榜.md查看排名」。
>
> ❌ #932 已作废（首次推送晚于机器人检查，被判缺文件），**不要在 #932 下回复任何内容**。

存档正文（如后续官方要求重新核验，可原样再提交）：

```
【参赛申请】
项目名称：麦麦省钱点单助手
项目地址：https://github.com/Huangxxuan/mcd-savings-skill
项目简介：会算账的麦当劳点单专家，用真实价格和优惠券算出省钱榜单最优解，一键领券 + 自动用最优券 + 卡路里可视 + 五大场景搭配 + 拼单凑单 + 门店导航，把 MCP 真实数据渲染成可点击的点单助手
```

> 💡 经验：以后任何「报名类 Issue」都必须在**仓库文件推完之后**再提交，否则机器人会在几秒内判定为空仓库。

**推送完整性自检**（改完东西想知道有没有真推上去）：

```bash
cd /Users/huang/WorkBuddy/2026-10-20-17-09-03/mcd-savings-skill
echo "本地 HEAD: $(git rev-parse HEAD)"
curl -s https://api.github.com/repos/Huangxxuan/mcd-savings-skill/commits/main | grep -m1 '"sha"'
# 两个 sha 必须完全一致
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

## 四、冲进前 100 的三步（**门槛 23 Star，当前 4**）

> 2026-10-21 13:00 官方榜单实测：第 100 名 = 23 Star，第 1 名 = 813 Star。
> 进榜即有实物周边（汉堡回车键 + 徽章）+ WorkBuddy 3,000 积分。**还差 19 颗，完全够得着。**

### 1. 仓库 Description 与 Topics（5 分钟）

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

### 3. 按排期发帖（决定 80% 的 Star）

| 日期 | 渠道 | 用哪版文案 | 目标 |
|---|---|---|---|
| **10/21（今天）** | 朋友圈 + 3 个技术群 | 版本 C 一句话 + GIF | 前 10–20 星 |
| 10/22（四） | CSDN 活动页评论区 + 掘金 | 版本 A 技术长文 | 搜索流量与同行认可 |
| 10/23（五） | 即刻 / 小红书 / 公众号 | 版本 B 产品向图文 | 破圈到非技术人群 |
| 10/24（六） | V2EX / 少数派 / Discord、TG、微信群 | 版本 A 精简版 | 周末流量高峰 |
| 10/25（日） | 全渠道倒计时提醒 | 版本 C 变体 | 最后冲刺 |

文案全文见 `麦当劳大赛-传播话术包.md`（含 13 条标题库、配图清单、Star 引导话术）。

---

## 五、终审检查清单（10-25 当天跑一遍）

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
