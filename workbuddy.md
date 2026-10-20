# workbuddy.md — WorkBuddy 对话上下文

> 本文件为「麦当劳开发者创新挑战赛（1024 程序员节 · m-code）」WorkBuddy 专项奖励提交材料，
> 记录本项目在腾讯 WorkBuddy 智能体中的真实开发过程，用于活动联动核验。

## 项目与账号

- **项目名称**：麦麦省钱点单助手（mcd-savings-skill）
- **项目地址**：`https://github.com/Huangxxuan/mcd-savings-skill`
- **开发方式**：全程在腾讯 WorkBuddy 智能体中，以自然语言对话驱动完成——从比赛规则解读、MCP Token 接入、
  数据管道编写、可视化页面开发到多轮交互打磨，未使用 WorkBuddy 之外的 AI 编码工具。

## 对话驱动的开发历程（真实上下文摘要）

### 第 1 轮：比赛解读与方案设计

用户提供了比赛仓库（`M-China/mcd-developer-innovation-challenge`）、活动页与截图，要求深度分析并输出 MVP 方案。
WorkBuddy 输出了《麦当劳MCP开发大赛-深度分析与MVP方案.md》：需求↔MCP 工具映射表、技术选型对比、
P0/P1/P2 排期、报名 Issue 模板与风险清单。关键结论：提交物除 README 外**必须**包含
`CONTEST_DECLARATION.md`（官方原样）与 `mcp-config.example.json`（仅环境变量占位符）。

### 第 2 轮：MCP 接入与全量工具验证

用户申请到 `open.mcd.cn/mcp` 的 Token 后，WorkBuddy 通过 Streamable HTTP + Bearer 认证接入
`https://mcp.mcd.cn`，实测 `tools/list` 返回 **35 个 Tool**（比官方 README 多出 `query-promotions`
与 `query-survey-coupons` 两个），逐一验证参数并沉淀进 `SKILL.md` 的速查表与踩坑记录
（beCode 传参规则、营养数据为紧凑文本、券不返回面额等）。

### 第 3 轮：真实数据链路与可视化页

WorkBuddy 编写 `scripts/build_data.py` 数据管道（定位门店 → 菜单 → 券 → 营养 → 提醒源 → 组装
`assets/data.js`），并产出单文件可视化点单页 `assets/order-assistant.html`。所有数据均为 MCP 实时返回：
5 家门店、110 餐品、61 条营养匹配、实时券列表。**纪律：匹配不到营养数据的显示「热量待核」，绝不编造。**

### 第 4 轮（迭代）：拼单分享 / 不错过提醒 / 3D 视觉 / 场景分类 / 祝福卡

用户以自然语言提出 5 项增强，WorkBuddy 全部落地：多人拼单分账与分享文案、5 类「优惠不错过」提醒聚合、
CSS 3D（perspective + preserve-3d 卡片、祝福卡 rotateY 翻转）、五大场景分类
（健康早餐/办公下午茶/儿童套餐/健身运动餐/悦己养颜餐 + 贪心+枚举推荐组合）、3D 翻转祝福提示卡。

### 第 5 轮（迭代）：场景↔菜单一致性 / 提醒侧栏 / 场景弹窗 / 终端风视觉

按用户截图反馈修复：点场景方案后菜单自动切分类并闪烁高亮（名称与 MCP 数据同源）；提醒收纳进右侧栏；
场景点击弹出推荐设置框（Top3 方案 + 卡路里预算 DIY 滑杆）；整体视觉定调
**Retro-futuristic Terminal HUD**（Space Mono / 麦当劳黄 #FFC72C / 青色 HUD 读数 / CRT 扫描线氛围）。

### 第 6 轮（迭代）：品牌页头 / 一键领券 / 自动用券 / 结算数字

还原麦当劳红渐变页头；新增「⚡ 一键领券」（复制 `auto-bind-coupons` 指令）与「自动用券」开关
（选品后自动试算启用最优券）；修复底部「原价 / 立省 / 应付 / 卡路里」显示。
期间定位并修复关键 Bug：**券接口与菜单接口是两套商品编码体系**，直接匹配导致立省恒为 ¥0，
通过名称回退匹配解决。

### 第 7 轮（迭代）：真实领券闭环 / 提醒点击选品 / workbuddy.md

- WorkBuddy 真实调用 `auto-bind-coupons`，**5 张可领券全部领取成功**（接口返回 couponId/couponCode）；
  重跑数据管道后，页面按 MCP 真实查询结果标注「已领取 / 未领取」状态；
- 券标题解析升级支持**特价券**（如「11.9元麦辣鸡腿堡」→ 麦辣鸡腿汉堡 ¥22.5 省 ¥10.6）与免费换购券；
- 「优惠不错过」提醒从纯展示升级为**可点击选品入口**：点击券提醒直接在菜单中定位并高亮对应产品；
- 补齐本 `workbuddy.md`。

### 第 8 轮（迭代）：复制指令反馈 / 商城订单接入 / 文档同步

- 修复「复制点单指令」点击无反馈：根因是 `navigator.clipboard` 在非安全上下文
  （`file://` 或未授权 iframe）下为 undefined，同步抛错导致整个处理函数中断。
  改为三级降级（Clipboard API → `execCommand('copy')` → 可视化指令框自动全选），
  并在页面底部常驻终端风输出框，保证**点击后一定能看到生成的指令**；
- 接入**麦麦商城订单查询**：`mall-order-list` + `mall-order-detail`（实测接口正常，当前账号 0 单，
  页面诚实显示空态与查询指引）；
- 完善一键领券：发现 `available-coupons` 接口**自带「状态：已领取/未领取」字段**，
  改为直采该字段（原先交叉比对把「免费脆薯饼」误判为未领取），保留交叉判定兜底；
- 券计算引擎补充**特价券 / 免费换购券**两类解析；
- 新增 `ROADMAP.md` 待办节点清单，同步 `SKILL.md` / `README.md` / `MCP_INTEGRATION.md` / `workbuddy.md`。

## WorkBuddy 能力使用清单

| 能力 | 用途 |
|---|---|
| 对话式需求分析与方案输出 | 比赛规则解读、MVP 方案、每轮迭代拆解 |
| MCP 连接（Streamable HTTP） | 直连麦当劳 MCP Server，35 个 Tool 全量验证 |
| 本地文件读写与代码工程 | SKILL.md / build_data.py / order-assistant.html / README 等 8 个交付文件 |
| Shell 执行与验证 | MCP 实时调用、数据管道构建、Node DOM 冒烟测试、计算准确性验证 |
| 前端可视化生成 | 单文件 HTML（CSS 3D、终端风视觉、状态驱动渲染） |
| 多轮上下文记忆 | 跨 8 轮迭代保持架构一致性与数据口径纪律 |

## 待办节点（详见 ROADMAP.md）

- **P0（10-25 前必做）**：轮换 MCP Token → 创建 GitHub 公开仓库 → 提交报名 Issue → 替换地址占位符 → 全仓查敏感信息；
- **P1（冲名次）**：录演示 GIF 放 README 首屏、强化首屏视觉、写传播文案；
- **P2（增强）**：页面内 `create-order` 下单、团餐满减与问卷券接入、营养匹配率提升、多门店缓存。

## 质量验证（WorkBuddy 自动化执行）

- HTML 标签平衡 / JS 语法 / 59 个 DOM id 引用完整性：全部通过；
- DOM 级运行时冒烟：初始化渲染、场景应用、券自动择优、特价券折扣均验证通过；
- 计价抽查（4/4 通过）：7 折券 ¥11.9 → 省 ¥3.57；特价券 ¥22.5 − ¥11.9 → 省 ¥10.60；
  多券同单选自动择优（max(10.60, 3.57, 2.00) = 10.60）；买一送一等无法解析的券诚实显示 ¥0；
- 一键领券实测：`auto-bind-coupons` 成功领 5 张（总计 5 / 成功 5 / 失败 0），返回 couponId + couponCode；
  `available-coupons` 自带「状态：已领取/未领取」字段，页面直采该字段显示；
- 商城订单实测：`mall-order-list` / `mall-order-detail` 接口正常（当前账号 0 单，页面显示空态）。
