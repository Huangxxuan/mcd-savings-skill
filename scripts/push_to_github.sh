#!/usr/bin/env bash
# ==============================================================================
# push_to_github.sh — 把参赛项目推送到 GitHub 公开仓库
#
# 用法:
#   ./scripts/push_to_github.sh
#
# 设计原则（安全优先）：
#   - 幂等：重复执行不会出错或产生重复提交
#   - 不强制推送：绝不执行 --force / --force-with-lease
#   - 推送前必做敏感信息扫描，发现密钥立即中止
#   - 仓库若非空且历史不相关，会提示并中止，避免覆盖他人/既有内容
#
# 凭证：本机会走 osxkeychain；用户名填 GitHub 用户名，密码填
#       **Personal Access Token**（GitHub 已不支持账户密码推送）
# ==============================================================================
set -euo pipefail

REPO_URL="https://github.com/Huangxxuan/mcd-savings-skill.git"
BRANCH="main"

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[0;33m'; NC='\033[0m'
say()  { echo -e "${GRN}▸${NC} $1"; }
warn() { echo -e "${YEL}⚠${NC}  $1"; }
die()  { echo -e "${RED}✗${NC} $1"; exit 1; }

# ---- 0. 目录定位 ----
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
say "项目目录: $ROOT"

# ---- 1. 敏感信息扫描 ----
say "扫描敏感信息..."
if grep -rInE "Bearer [A-Za-z0-9_-]{12,}|MCD_MCP_TOKEN *= *[\"'][A-Za-z0-9]" \
     --exclude-dir=.git --exclude=mcp-config.example.json . 2>/dev/null; then
  echo "--- 命中内容 ---"
  grep -rInE "Bearer [A-Za-z0-9_-]{12,}|MCD_MCP_TOKEN *= *[\"'][A-Za-z0-9]" \
     --exclude-dir=.git --exclude=mcp-config.example.json . 2>/dev/null || true
  die "检测到疑似密钥，已中止推送。请先清除后再试。"
fi
echo "✅ 未发现密钥明文"

# ---- 2. 必需提交物检查 ----
say "检查官方要求的提交物..."
MISSING=0
for f in README.md CONTEST_DECLARATION.md MCP_INTEGRATION.md mcp-config.example.json SKILL.md workbuddy.md; do
  if [ -f "$f" ]; then
    echo "  ✅ $f"
  else
    echo "  ❌ 缺失 $f"
    MISSING=1
  fi
done
[ "$MISSING" -eq 0 ] || die "缺少必需文件，请补齐后再推送。"

# ---- 3. git 仓库初始化（幂等）----
if [ ! -d ".git" ]; then
  say "初始化 git 仓库..."
  git init -q
else
  say "git 仓库已存在，跳过初始化"
fi

# ---- 4. 身份配置（幂等，仅在缺失时设置）----
if [ -z "$(git config --get user.name 2>/dev/null || true)" ]; then
  echo -n "请输入 GitHub 用户名: "
  read -r GH_USER
  git config user.name "$GH_USER"
fi
if [ -z "$(git config --get user.email 2>/dev/null || true)" ]; then
  echo -n "请输入 GitHub 注册邮箱: "
  read -r GH_MAIL
  git config user.email "$GH_MAIL"
fi
say "提交身份: $(git config --get user.name) <$(git config --get user.email)>"

# ---- 5. 分支（幂等）----
git branch -M "$BRANCH" 2>/dev/null || true

# ---- 6. 暂存并提交（无改动则跳过）----
git add .
if git diff --cached --quiet; then
  say "无待提交改动"
else
  git commit -q -m "feat: 麦麦省钱点单助手 — 基于麦当劳 MCP 的可视化点单 Skill

- 一键领券（auto-bind-coupons 真实调用）+ 已领取/未领取状态
- 自动用券：多券试算择优，支持满减/折扣/直减/特价/免费换购
- 五大场景搭配推荐 + 卡路里预算 DIY
- 拼单凑单分账与分享文案、凑单神器
- 优惠不错过提醒（可点击联动菜单选品）
- 麦麦商城订单列表与详情查询
- Retro-futuristic Terminal HUD 视觉 + CSS 3D + 祝福提示卡"
  say "✅ 本地提交完成"
fi

# ---- 7. remote（幂等）----
if git remote get-url origin >/dev/null 2>&1; then
  say "remote origin 已存在: $(git remote get-url origin)"
else
  say "添加 remote origin: $REPO_URL"
  git remote add origin "$REPO_URL"
fi

# ---- 8. 推送（不强制）----
say "推送到 origin/$BRANCH ..."
if git push -u origin "$BRANCH"; then
  echo ""
  echo -e "${GRN}✅ 推送成功${NC}"
  echo "   仓库: https://github.com/Huangxxuan/mcd-savings-skill"
else
  echo ""
  warn "推送失败，常见原因与处理："
  echo "  1) 认证失败 → 密码处请填 Personal Access Token（不是账户密码）"
  echo "     生成地址：https://github.com/settings/tokens （勾选 repo 权限）"
  echo "  2) 远端非空（如已有 README）→ 先合并："
  echo "     git pull --rebase origin $BRANCH && git push -u origin $BRANCH"
  echo "  3) 网络/代理 → 换网络或关闭代理后重试"
  exit 1
fi
