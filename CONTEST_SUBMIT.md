# 参赛提交材料：建仓命令清单 + 报名 Issue 文案

> 关键时间点：**2026-10-25 23:59 报名截止** ｜ **2026-10-26 00:00 定榜**
> 排名规则：纯按 GitHub 公开 **Star 数**（无评委评审）

---

## 一、建仓命令清单（按顺序复制执行）

### 步骤 1：在 GitHub 网页端创建空仓库（2 分钟）

1. 打开 <https://github.com/new>
2. **Repository name** 填：`mcd-savings-skill`（你已建好，此步可跳过）
3. 选 **Public**（必须公开，否则无法入榜）
4. **不要**勾选 "Add a README file" / ".gitignore" / "license"（保持完全空仓库，避免首次推送冲突）
5. 点 **Create repository**

### 步骤 2：本地初始化并推送

在你的项目目录执行（用户名已按 `Huangxxuan` 填好，可直接复制）：

```bash
# 进入项目目录
cd /Users/huang/WorkBuddy/2026-10-20-17-09-03/mcd-savings-skill

# 初始化仓库
git init

# 配置身份（如已全局配置可跳过）
git config user.name  "Huangxxuan"
git config user.email "你的邮箱@example.com"

# 确认主分支名与 GitHub 一致
git branch -M main

# 添加全部文件
git add .

# ⚠️ 提交前务必确认没有敏感信息（见下方检查命令）
git status

# 首次提交
git commit -m "feat: 麦麦省钱点单助手 — 基于麦当劳 MCP 的可视化点单 Skill

- 一键领券（auto-bind-coupons，实测领取 5 张成功）
- 自动用券：多券试算择优，支持满减/折扣/直减/特价/免费换购
- 五大场景搭配推荐 + 卡路里预算 DIY
- 拼单凑单分账与分享文案
- 优惠不错过提醒（可点击联动菜单选品）
- 麦麦商城订单列表与详情
- Retro-futuristic Terminal HUD 视觉 + CSS 3D + 祝福提示卡"

# 关联远程仓库
git remote add origin https://github.com/Huangxxuan/mcd-savings-skill.git

# 推送
git push -u origin main
```

**预期输出**：`Enumerating objects... Writing objects: 100%` → `branch 'main' set up to track 'origin/main'`

### 步骤 3：推送前的安全检查（**必做**）

```bash
# 检查 1：确认工作区无敏感文件
git status --porcelain

# 检查 2：确认没有 Token 明文被暂存
git diff --cached | grep -iE "token|secret|password" || echo "✅ 无敏感信息"

# 检查 3：确认 mcp-config.example.json 只含占位符
cat mcp-config.example.json
# 期望：{"mcpServers":{"mcd-mcp":{"type":"streamablehttp","url":"https://mcp.mcd.cn","headers":{"Authorization":"Bearer ${MCD_MCP_TOKEN}"}}}}
```

---

## 二、报名 Issue 文案（**严格按官方格式**）

### 官方格式要求（务必遵守）

- ✅ 每个字段**各占一行**，字段内部**不换行**
- ✅ **项目地址不要用 Markdown 链接语法**（不要 `[xxx](url)`，直接写裸 URL）

### 复制以下内容（Title 和 Body 分别填）

**Issue Title：**
```
【参赛申请】麦麦省钱点单助手
```

**Issue Body：**
```
【参赛申请】
项目名称：麦麦省钱点单助手
项目地址：https://github.com/Huangxxuan/mcd-savings-skill
项目简介：会算账的麦当劳点单专家，一键领券 + 自动用最优券 + 卡路里可视 + 场景搭配 + 拼单凑单 + 门店导航，把 MCP 真实数据渲染成可点击的点单助手
```

### 提交入口

- 活动页：<https://builderx.csdn.net/activity-site/m-code/pages>
- 在 **M-China/mcd-developer-innovation-challenge** 仓库点 **New Issue** → 选择**参赛申请模板** → 粘贴上面内容 → Submit

---

## 三、仓库资料设置（建仓后 1 分钟，强烈建议）

**Description（仓库描述，填这句）：**
```
🍔 基于麦当劳中国 MCP 的可交互可视化点单 Skill：一键领券 · 自动用最优券 · 卡路里可视 · 五大场景搭配 · 拼单凑单 · 门店导航
```

**Topics（标签，提升搜索曝光）：**
```
mcdonalds    mcp    model-context-protocol    workbuddy    skill
1024        m-code   ai-agent    可视化      点单
```

**README 首屏占位（录好 GIF 后替换 `demo.gif`）：**
```html
<p align="center">
  <img src="./assets/demo.gif" width="820" alt="麦麦省钱点单助手演示">
</p>
```

---

## 四、提交前最终检查清单

| # | 检查项 | 命令/方式 | 期望 |
|---|---|---|---|
| 1 | 仓库为 Public | GitHub 页面确认 | ✅ 非 Private |
| 2 | 无 Token 明文 | `git grep -n "Bearer " -- .` | 无结果 |
| 3 | `mcp-config.example.json` 仅占位符 | `cat mcp-config.example.json` | 只有 `${MCD_MCP_TOKEN}` |
| 4 | `CONTEST_DECLARATION.md` 原样未改 | 对比官方文件 | 内容一致 |
| 5 | `workbuddy.md` 已存在且地址真实 | 打开文件 | 专项奖必需 ✅ |
| 6 | 页面可独立打开 | 双击 `assets/order-assistant.html` | 正常渲染 |

### 一键自检命令

```bash
cd /Users/huang/WorkBuddy/2026-10-20-17-09-03/mcd-savings-skill

echo "--- 1. 敏感信息扫描 ---"
grep -rInE "Bearer [A-Za-z0-9]{10,}" . 2>/dev/null | grep -v "example.json" || echo "✅ 安全"

echo "--- 2. 必需文件 ---"
for f in README.md CONTEST_DECLARATION.md MCP_INTEGRATION.md mcp-config.example.json SKILL.md workbuddy.md; do
  [ -f "$f" ] && echo "✅ $f" || echo "❌ 缺失 $f"
done

echo "--- 3. 占位符检查 ---"
grep -rn "你的GitHub用户名\|<用户名>" README.md workbuddy.md 2>/dev/null || echo "✅ 无残留占位符"
```
