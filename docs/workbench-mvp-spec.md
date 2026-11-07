# 网页工作台 MVP 规格（v0，2026-11-05）

> 目标：3–5 名客服试用，产出**采纳率**与**AHT**两个业务指标，并沉淀"AI 答不好 / 人工改了什么"的知识缺口周报。

---

## 1. 目标与验收

| 项 | 定义 |
|---|---|
| 使用者 | 3–5 名客服（新人 ≥1、老员工 ≥2） |
| 周期 | 连续 10 个工作日 |
| 成功标准 | 采纳率 ≥ 60%；AHT 相对基线下降 ≥ 15%；无用率 ≤ 15%；周报能自动产出 ≥ 10 条知识缺口 |
| 交付物 | 可演示的网页工作台 + 周报 + 可对外的指标数字 |

---

## 2. 页面与交互

单页三栏，不做路由跳转：

```
┌─────────────────────────────────────────────────────────────┐
│ 顶栏：工号 / 新人·老人切换 / 今日已用 12 次                  │
├──────────────────────┬──────────────────────────────────────┤
│ 左：输入区            │ 右：回答卡片                          │
│ 买家原话 [textarea]   │ ┌ 建议回复（可编辑）──────────────┐  │
│ 场景 [下拉，默认 auto]│ │ 您好，……                        │  │
│ 订单号 [input，可选]  │ └────────────────────────────────┘  │
│ [生成建议]            │ 依据：06_shipping_policy「四、签收」  │
│                      │ 动作：直接回复  转主管：否            │
│                      │ [复制] [标记无用] [保存修改]          │
├──────────────────────┴──────────────────────────────────────┤
│ 底部：本次耗时 42s · 模型 8.9s · 反馈：[有用][没用] [备注]    │
└─────────────────────────────────────────────────────────────┘
```

交互规则：

1. **粘贴即开始计时**：`session_started_at` 记录在"买家原话"输入框首次获得焦点时；
2. **卡片可编辑**：默认展示 AI 原文，员工改动后点"保存修改"，系统记录 diff；
3. **三个动作**：复制（采纳）、保存修改（改后采纳）、标记无用（不采纳）；
4. **新人/老人**：切到"新人"时卡片多显示"为什么这么说"；老人隐藏；
5. **失败态**：Dify 超时/JSON 坏 → 卡片显示"生成失败，请重试或手动回复"，不白屏。

---

## 3. 计时口径（AHT 的关键）

AHT 不是模型耗时，是**员工从看到问题到发出回复的总时间**。

- 计时起点：员工把买家消息粘贴进输入框（`focus` 事件）；
- 计时终点：点"复制"或"保存修改"（发出回复的动作）；
- 记录字段：`session_started_at`、`session_ended_at`、`aht_seconds = end - start`；
- 兜底：若员工没点按钮就关闭页面，该条标记 `abandoned`，不计入 AHT 均值，但计入"未采纳"；
- 基线：试点前一周，同 3–5 人用现有方式（复制到 IM 手工回复）抽 20 条/人/天，秒表或录屏计时，得到基线 AHT。

> 为什么强调这个：模型 8.9s 和 AHT 40s 是两回事，对外写"AHT 从 X 降到 Y"必须能说清计时边界，否则会被追问穿。

---

## 4. 数据模型

### 4.1 conversations（每次生成一行）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | |
| agent_id | text | 工号 |
| agent_level | text | new / veteran |
| scene | text | 员工选的场景或 auto |
| scene_detected | text | 模型路由结果 |
| order_no | text | 可空 |
| query | text | 买家原话（手机号/地址脱敏） |
| reply | text | AI 建议回复 |
| evidence | jsonb | 依据数组（文档名+片段） |
| next_action | text | 直接回复/追问订单号/追问产品/查库存/查物流/转主管 |
| escalate | bool | |
| latency_ms | int | Dify 耗时 |
| status | text | copied / modified / useless / abandoned |
| final_text | text | 员工最终发出的话术（改过才有） |
| edit_distance | int | 与 AI 原文的字符级编辑距离 |
| feedback_note | text | 员工备注 |
| session_started_at / session_ended_at | timestamptz | |
| aht_seconds | int | 见第 3 节 |
| dify_message_id | text | 便于回溯 |

### 4.2 knowledge_gaps（周报的原料）

| 字段 | 说明 |
|---|---|
| id / conversation_id | |
| gap_type | no_kb（知识库没有）/ wrong_kb（答错）/ outdated（过期）/ wording（话术不合适）/ routing（路由错） |
| scene | |
| summary | 一句话描述缺口 |
| suggested_fix | 建议补什么（文档/条款/话术） |
| week | 2026-W45 |
| status | open / fixed |

生成规则（先规则、后人工）：

1. `status=useless` → `gap_type` 默认 `no_kb` 或 `wrong_kb`（由备注关键词判断：没有/查不到→no_kb；答错/不对→wrong_kb）；
2. `status=modified` 且 `edit_distance > 20` → `wording` 或 `wrong_kb`；
3. 同一 scene 一周内同类 gap ≥ 3 条 → 周报里合并为一条"高频缺口"。

---

## 5. API（网关）

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/api/ask` | buyer_message, order_no, agent_level, scene_hint | reply/evidence/next_action/escalate/latency_ms/message_id |
| POST | `/api/result` | conversation_id, status, final_text, note, started_at, ended_at | ok |
| POST | `/api/feedback` | conversation_id, useful(bool), note | ok |
| GET | `/api/health` | — | ok |

鉴权：登录后发 `session` 或 JWT；`agent_id` 从会话取，前端不能伪造。

---

## 6. 周报（每周五自动生成）

输出 `reports/weekly/2026-W45.md` + `.xlsx`，固定四段：

1. **用量**：会话数、活跃员工、人均次数、P50/P95；
2. **质量**：采纳率、修改率、无用率、按场景拆；
3. **知识缺口 Top 10**：gap_type、场景、原话摘要、建议补什么；
4. **下周动作**：3 条以内，写清谁在什么时候补哪份文档。

样例（占位）：

```
本周 412 次会话，5 人使用，人均 82 次
采纳率 63.1%（复制 48.2% + 修改后采纳 14.9%）
无用率 12.4%，最高：物流（18 条）、技术（11 条）
缺口 Top1：物流「改地址」口径，9 条，建议补 06 文档「已发货改地址」条款
```

---

## 7. 指标定义

| 指标 | 公式 | 备注 |
|---|---|---|
| 采纳率 | (copied + modified) / (copied + modified + useless) | abandoned 不计入分母 |
| 修改率 | modified / (copied + modified) | 衡量话术贴合度 |
| 无用率 | useless / 总有效会话 | |
| AHT | 中位数（abandoned 剔除） | 同时报 P50/P90，避免均值被长尾拉偏 |
| 单会话成本 | token 费用 / 会话数 | 可选 |

> 只用中位数报 AHT，均值放附录；样本 < 30 时不给结论，只给区间。

---
