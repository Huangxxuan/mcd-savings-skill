# 🍔 麦麦省钱点单助手 · mcd-savings-assistant

> 项目地址：https://github.com/Huangxxuan/mcd-savings-skill
> 会算账的麦当劳点单专家：一键领券 · 自动用最优券 · 智能搭配 · 卡路里可视 · 附近门店导航 · DIY 自由搭 · 一键下单

基于 **麦当劳中国 MCP**（`https://mcp.mcd.cn`）能力开发的可交互可视化 Skill。
它不只是一个聊天机器人——它会把 MCP 返回的真实菜单、优惠券、营养与门店数据，渲染成一个**可点击、可勾选、实时算价算热量**的 HTML 点单助手。

[![Powered by McDonald's MCP](https://img.shields.io/badge/Powered%20by-McDonald's%20MCP-DA291C)](https://open.mcd.cn/mcp)
[![Built with WorkBuddy](https://img.shields.io/badge/Built%20with-WorkBuddy-0052D9)](https://www.workbuddy.cn)

---

## ✨ 核心能力

| 能力               | 说明                                                                       | 依赖 MCP Tool                                                                                                |
| ---------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| 💰 **一键领券**      | 真实调用 `auto-bind-coupons` 领完当前所有可领券；页面按 MCP 返回标注「已领取 / 未领取」，并告诉你哪些能用在当前门店 | `auto-bind-coupons` / `available-coupons` / `query-store-coupons` / `query-my-coupons`                     |
| 🧮 **省钱最优搭配**    | 给定预算，枚举「主食×小食×饮品」，输出省得最多的 Top 3 方案                                       | `query-meals` / `calculate-price`                                                                          |
| 🔥 **控卡搭配**      | 给定热量上限（如 500 kcal），推荐蛋白质最优的组合，并显示营养结构                                    | `list-nutrition-foods`                                                                                     |
| 🎨 **DIY 自由搭**   | 全菜单勾选，套餐内可替换项自由换，实时联动总价与总热量                                              | `query-meal-detail`                                                                                        |
| 📍 **附近门店 + 导航** | 按距离排序，一键唤起导航到店，含营业时间与配送费                                                 | `query-nearby-stores` / `delivery-query-stores`                                                            |
| 🧾 **下单闭环**      | 生成点单指令（先 `calculate-price` 核价，再 `create-order`），支持取消与查单                  | `create-order` / `cancel-order` / `query-order`                                                            |
| 📦 **麦麦商城订单**    | 查询商城订单列表与详情，点击卡片展开商品明细与实付金额                                              | `mall-order-list` / `mall-order-detail`                                                                    |
| 👥 **拼单凑单分享**    | 多人各自选品、按人分账、人均金额；自动算「还差多少起送」并推荐补差商品；一键生成分享文案                             | `calculate-price` + 本地枚举                                                                                   |
| 🔔 **优惠不错过提醒**   | 券临期 / 可领未领 / 积分过期 / 抽奖机会 / 进行中活动，五类提醒按紧急度排序                              | `query-my-coupons` / `available-coupons` / `query-my-account` / `query-lottery-info` / `campaign-calendar` |
| ✨ **祝福提示卡**      | 选完餐生成 3D 翻转祝福卡，按场景/热量/省钱/拼单动态生成情绪价值文案                                    | 本地生成                                                                                                       |

**一切数据来自 MCP 实时返回，零编造。**

---

## 🎨 视觉与交互

**方向：Retro-futuristic Terminal HUD（复古未来 / 终端风）**

- **配色**：近黑蓝底 `#070B10`（60%）+ 表面层 `#0E141C`（30%）+ 麦当劳黄 `#FFC72C` 作唯一强调色（10%）；青色 `#00E5FF` 专用于数据读数，红色 `#FF5A5A` 仅用于告警。
- **字体**：Space Mono（展示字，等宽终端感）+ JetBrains Mono（等宽数字 `tabular-nums`）+ Noto Sans SC（中文正文）。
- **CSS 3D**：`perspective` + `transform-style: preserve-3d`，卡片悬停沿 X/Y 轴倾斜、按下物理回弹，祝福卡 `rotateY(180deg)` 翻转。
- **氛围层**：四层叠加——网格底纹 + 径向霓虹光晕 + CRT 扫描线 + 暗角。
- **入场编排**：一次性错峰揭示序列（3–6 组，间隔 90ms），而非零散微交互。

**交互约定：**

| 操作     | 效果                                                                 |
| ------ | ------------------------------------------------------------------ |
| 点场景卡   | 弹出终端推荐框：Top3 方案 + 卡路里预算 DIY 滑杆                                     |
| 点方案 N  | 应用到当前点单人，菜单自动切到对应分类并闪烁高亮                                           |
| 点商品卡   | 加入 / 移出当前点单人                                                       |
| 点券类提醒  | 直接在菜单中定位并高亮对应产品（如点「免费脆薯饼」→ 高亮薯饼类单品）                                |
| ⚡ 一键领券 | 复制 `auto-bind-coupons` 指令给 AI，或重跑 `build_data.py --claim` 真实领取     |
| 领取状态   | 「已领取 / 未领取」来自 MCP 真实查询（`query-my-coupons` + `query-store-coupons`） |
| 选品后    | 自动试算所有可用券，默认启用最优的一张（可切手动开关）                                        |
| 点优惠券   | 手动开关并实时重算应付；手动干预即退出自动用券                                            |
| 点门店卡   | 切换门店；「导航到店」跳转高德                                                    |
| 点拼单人   | 切换当前点单人，各自选品分账                                                     |
| 未达起送   | 给出「凑单神器」补差推荐 + 进度条                                                 |

> ⚠️ **数据口径说明**：麦当劳 MCP 的 `list-nutrition-foods` 只覆盖约 158 种常见餐品，新品/组合餐（如「龙焰芝士棒鸡腿堡」「奶香大米派」「BFF 四宫格小食盘」）无官方热量数据。匹配分三档，页面如实标注——**不编造任何营养数据**：
>
> | 档位   | 规则                                       | 页面显示          | 实测数量     |
> | ---- | ---------------------------------------- | ------------- | -------- |
> | 精确   | 名称归一化后完全一致/互相包含                          | `🔥 391 kcal` | 54 / 108 |
> | 规格归一 | 去掉「中杯/大杯/热/冰/™」后核心名一致（如「麦咖啡™美式」→「冰美式中杯」） | `🔥 ≈13 kcal` | 7 / 108  |
> | 未匹配  | 三档皆不中                                    | `热量待核`        | 47 / 108 |

---

## 🚀 快速开始（3 步）

### 第 1 步：申请 MCP Token

1. 打开 <https://open.mcd.cn/mcp> ，点击右上角【登录】
2. 使用手机号验证码登录
3. 点击右上角【控制台】→【激活】，申请 MCP Token
4. 同意服务协议后即可一键复制 Token

### 第 2 步：配置 MCP 连接器

在任意支持 Streamable HTTP 的 MCP Client（推荐 [WorkBuddy](https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Connector)、Cursor、Cherry Studio、Trae）中填入：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

> ⚠️ 记得把 `YOUR_MCP_TOKEN` 替换为你的真实 Token，并妥善保管，切勿提交到任何仓库。

### 第 3 步：安装 Skill 并说话

把本仓库 `SKILL.md` 放入你的 Skill 目录，然后直接说：

| 你说                     | 助手做什么                                     |
| ---------------------- | ----------------------------------------- |
| 「我在深圳南山科技园，30 块怎么吃最划算」 | 定位门店 → 领券 → 枚举组合 → 输出 3 套省钱方案 + HTML 可视化页 |
| 「500 大卡能吃什么，要蛋白质高的」    | 按热量预算搭配，展示营养结构                            |
| 「我要自己配，巨无霸换板烧，薯条换玉米」   | 展示可替换项，实时算价算热量                            |
| 「就按方案 1 下单，外送」         | 核价 → `create-order` → 返回官方支付链接            |

---

## 📁 项目结构

```
mcd-savings-assistant/
├── SKILL.md                     # Skill 主文件（触发词 + 五阶段工作流）
├── README.md                    # 本文件
├── CONTEST_DECLARATION.md       # 参赛声明（官方文件，内容未改动）
├── MCP_INTEGRATION.md           # MCP 集成说明（Server / Tools / 流程 / 价值）
├── mcp-config.example.json      # 脱敏 MCP 配置示例（仅环境变量占位符）
├── workbuddy.md                 # WorkBuddy 开发对话上下文
└── assets/
    ├── order-assistant.html     # 可视化交互点单页（券开关/热量条/DIY勾选/门店导航）
    └── store-map.html           # 门店地图页
```

---

## 🏗️ 技术实现

- **Skill 层**：`SKILL.md` 定义触发词与五阶段工作流（定位 → 领券 → 取菜单营养 → 搭配渲染 → 下单），约束模型必须真实调用 MCP、禁止臆造数据。
- **数据层**：每次会话拉取一次 `query-meals` + `list-nutrition-foods`，合并为本地缓存映射。
- **推荐算法**：预算/热量约束下的组合枚举（贪心 + 剪枝），本地初筛后仅对 Top 3 调用 `calculate-price` 精算，单次会话 MCP 调用 < 10 次，规避 600 次/分钟限流。
- **可视化层**：单页 HTML，纯原生 JS 实现状态驱动渲染——选品、券开关、模式切换、门店选择全部实时联动「原价 / 立省 / 应付 / 总热量」。
- **闭环**：用户确认 → `create-order` → 麦当劳官方支付链接（本项目不接触任何支付信息）。

---

## ⚠️ 免责声明

- 本项目为「麦当劳程序员创意开发大赛」参赛作品，**由参赛者独立开发，非麦当劳官方产品**；
- 营养数据来自麦当劳 MCP，仅供参考，**不构成医疗或营养建议**；
- 餐品信息、价格及供应状态**以麦当劳官方渠道的实时结果为准**；
- 使用麦当劳 MCP 服务须遵守《麦当劳 MCP 服务规则》及《使用条款》。

© 2026 McDonald's. All Rights Reserved. 本项目仅用于参赛与技术交流。
