#!/usr/bin/env bash
# ==============================================================================
# mcp_call.sh — 调用麦当劳 MCP Server 的任意 Tool
#
# 用法:
#   export MCD_MCP_TOKEN='你的Token'
#   ./scripts/mcp_call.sh <toolName> '<JSON 参数>'
#
# 示例:
#   ./scripts/mcp_call.sh now-time-info '{}'
#   ./scripts/mcp_call.sh query-nearby-stores '{"beType":1,"searchType":2,"city":"深圳市","keyword":"科技园"}'
#   ./scripts/mcp_call.sh query-meals '{"storeCode":"xxx","beType":1,"orderType":1}'
#
# 注意: 请勿将 Token 写入本文件或提交到仓库。
# ==============================================================================
set -euo pipefail

TOKEN="${MCD_MCP_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  echo "错误: 未设置环境变量 MCD_MCP_TOKEN" >&2
  echo "用法: export MCD_MCP_TOKEN='你的Token' && $0 <toolName> '<JSON 参数>'" >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "用法: $0 <toolName> '[JSON 参数]'" >&2
  exit 1
fi

TOOL="$1"
ARGS="${2:-{\}}"

curl -sS -X POST https://mcp.mcd.cn \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d "$(printf '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"%s","arguments":%s}}' "$TOOL" "$ARGS")"
