# MCP 集成说明（MCP_INTEGRATION）

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 提供方 | 麦当劳中国（金拱门（中国）有限公司） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | HTTP Header `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| 开放平台 | https://open.mcd.cn/mcp |
| 集成指南仓库 | https://github.com/M-China/mcd-mcp-server |
| 限流 | 600 次请求 / 分钟（超限返回 429） |

配置示例见 [`mcp-config.example.json`](./mcp-config.example.json)，**仅包含环境变量占位符，不含任何真实凭证**。

## 2. 实际使用的 Tools 与调用流程

### 2.1 工具清单（按业务域）

| 业务域 | Tool | 在本项目中的作用 |
|---|---|---|
| 门店 | `query-nearby-stores` | 到店/自取场景查询附近门店，输出距离、地址、营业时间 |
| 门店 | `delivery-query-addresses` | 外送场景获取用户已保存的配送地址 |
| 门店 | `delivery-query-stores` | 外送场景查询可配送门店与起送/配送费 |
| 优惠 | `auto-bind-coupons` | 一键领取麦麦省当前全部可领券（省钱第一步） |
| 优惠 | `query-store-coupons` | 查询指定门店可用券，用于券适配 |
| 优惠 | `query-my-coupons` | 查询账户下全部优惠券 |
| 优惠 | `campaign-calendar` | 查询当月活动日历（1+1、随心配等），纳入推荐 |
| 菜单 | `query-meals` | 获取门店当前可售菜单（分类/餐品编码/标签/价格） |
| 菜单 | `query-meal-detail` | 获取套餐组成与可替换项（DIY 与搭配必需） |
| 营养 | `list-nutrition-foods` | 获取能量/蛋白质/脂肪/碳水/钠/钙，支撑卡路里与营养结构展示 |
| 交易 | `calculate-price` | 带券核价（商品金额 + 配送费 - 优惠 = 应付） |
| 交易 | `create-order` | 创建订单，返回订单详情与**官方支付链接** |
| 交易 | `cancel-order` | 取消订单 |
| 交易 | `query-order` / `order-list` | 查询订单状态与历史订单 |

### 2.2 调用流程

```
① 定位门店
   delivery-query-addresses → delivery-query-stores   （外送）
   query-nearby-stores                                （到店/自取）

② 领券读券
   auto-bind-coupons → query-store-coupons / query-my-coupons → campaign-calendar

③ 取菜单与营养
   query-meals（+ query-meal-detail 取套餐组成与替换项）
   list-nutrition-foods
   → 本地合并为「code → { price, kcal, protein, fat, carb }」缓存

④ 智能搭配（本地枚举 + MCP 精算）
   按预算/热量约束枚举 主食×小食×饮品 组合
   → 本地初筛 Top 3
   → 仅对 Top 3 调用 calculate-price（带券）精算
   → 渲染 assets/order-assistant.html

⑤ 下单
   用户确认 → calculate-price 最终核价 → create-order → 返回支付链接
   （取消：cancel-order；查询：query-order / order-list）
```

### 2.3 限流规避策略（关键）

- 菜单（`query-meals`）与营养（`list-nutrition-foods`）**每次会话仅拉取一次并缓存**；
- 组合枚举与排序在**本地缓存**上完成，不逐个调用 MCP；
- 只有进入 Top 3 的候选组合才调用 `calculate-price`，单次会话 MCP 调用量稳定在 **10 次以内**，远低于 600 次/分钟；
- 捕获 429 时提示降频重试，捕获 401 时提示 Token 失效。

### 2.4 新增功能对应的工具链

**拼单凑单分享**
```
delivery-query-stores / query-nearby-stores  → 取起送价与配送费门槛
query-meals                                   → 取可补差商品与价格
calculate-price                               → 核价（合并多人的商品清单）
→ 本地计算差额与人均金额，生成分享文本
```

**优惠不错过提醒**
```
query-my-coupons     → 券有效期 → 临期提醒（≤3天 danger / ≤7天 warn）
available-coupons    → 接口自带「状态：已领取/未领取」→ 可领未领提醒（warn）
query-my-account     → 本月/下月过期积分 → 积分过期提醒
query-lottery-info   → 活动状态与消耗规则 → 抽奖机会提醒
campaign-calendar    → 进行中/未来活动 → 活动提醒
query-my-prizes      → 已中奖未核销 → 奖品待用提醒
```

**一键领券（写操作）**
```
auto-bind-coupons    → 无需参数，自动领取全部可领券
                       → 返回「总计 5 张 / 成功 5 张 / 失败 0 张」+ couponId + couponCode
available-coupons    → 复查状态（自带领取状态字段；有延迟属正常）
→ 命令行：MCD_MCP_TOKEN=… python3 scripts/build_data.py --claim
```

**麦麦商城订单查询**
```
mall-order-list      → size ≤ 10 / lastId 翻页 → 订单摘要（orderId、状态、件数、商品）
mall-order-detail    → orderId（必填）→ 商品明细、下单时间、实付金额
→ 写入快照 orders[]，页面「05 麦麦商城订单」面板展示，点击卡片展开详情
```

## 3. 业务价值

| 价值点 | 说明 |
|---|---|
| 省钱 | 一键领券 + 券适配 + 券后价对比，把「不知道有券 / 不会用券」变成「自动省最多」，单笔订单可省 5–15 元 |
| 省时 | 门店距离排序 + 一键导航，减少找店与排队决策成本 |
| 健康可控 | 卡路里预算约束搭配 + 蛋白质/脂肪/碳水结构可视化，让「控卡期吃麦当劳」有据可依 |
| 降低决策成本 | DIY 可视化勾选，实时联动总价与总热量，选择困难症友好 |
| 交易闭环 | 从推荐到 `create-order` 支付链接一站式完成，不是「只给建议」的空壳助手 |

## 4. 实测验证记录（2026-10-20）

通过 `tools/list` 与 `tools/call` 直连 `https://mcp.mcd.cn` 完成真实调用验证：

| 验证项 | 结果 |
|---|---|
| 工具总数 | **35 个**（比官方 README 工具表多出 `query-promotions`、`query-survey-coupon` 等） |
| 鉴权 | Bearer Token 生效，返回 200 |
| `query-nearby-stores`（深圳·科技园，beType=1，searchType=2） | ✅ 返回 5 家门店，含 storeCode / 地址 / distance(米) / 营业时间 / 预约时段 |
| `query-meals`（storeCode=1420762，beType=1，orderType=1） | ✅ 返回 15 个分类、108 个餐品，含分类、编码、价格、标签、图片、优惠类型 |
| `query-store-coupons` | ✅ 返回 5 张可用券（领取后），含 couponId / couponCode / 有效期 / 适用商品编码 |
| `list-nutrition-foods` | ✅ 返回 158 条营养数据（紧凑文本格式） |
| `available-coupons` | ✅ 返回 5 张可领券，含「状态：已领取/未领取」字段 |
| `auto-bind-coupons` | ✅ 一键领券成功：总计 5 / 成功 5 / 失败 0，返回 couponId + couponCode |
| `mall-order-list` | ✅ 接口正常（当前账号返回空订单列表） |
| `mall-order-detail` | ✅ 参数 `orderId`（必填），有订单时返回商品明细与实付金额 |
| `query-my-account` | ✅ 返回积分账户（当前可用积分 0） |
| `query-lottery-info` | ✅ 返回抽奖活动状态与消耗规则 |
| `campaign-calendar` | ✅ 返回当日/往期/未来活动（含「麦当劳 X PEACEMINUSONE」联名等） |
| `now-time-info` | ✅ 返回服务器时间 |

**验证中发现的关键限制（见 SKILL.md「实测踩坑记录」）**：
1. 门店接口**不返回真实经纬度**（恒为 0.0），地图功能需自建地理编码；
2. 营养数据是**紧凑文本**而非 JSON，需自行解析并按名称模糊匹配；
3. 优惠券**不返回面额**，精确金额须由 `calculate-price` 核出；
4. `beCode` 传参规则严格（到店自取不可传，外送/得来速/团餐必传），传错直接报错。

## 5. 合规声明

- 本项目为「麦当劳程序员创意开发大赛」参赛作品，**非麦当劳官方产品**；
- 所有餐品、价格、优惠、营养、门店数据均来自麦当劳 MCP 实时返回，本项目不做任何缓存沉淀或二次分发；
- 支付环节跳转麦当劳官方页面完成，本项目不接触、不存储任何支付信息；
- 营养数据仅供参考，不构成医疗或营养建议。
