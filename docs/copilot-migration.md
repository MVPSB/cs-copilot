# 内部客服副驾迁移清单（v2）

目标：把对外客服版 Chatflow 改成员工用的"客服副驾"——输出结构化 JSON（话术 + 依据 + 是否升级），并按新老员工给不同解释。

**v2 修正了 v1 的一个坑**：Dify 要求 LLM 节点的 user 消息必须引用 `sys.query`，v1 把 user 消息换成了 buyer_message 变量，导入后直接报"user message 中必须包含 sys.query"。v2 改成：

- **买家原话 = 对话输入 `sys.query`**（员工直接在聊天框粘贴）
- 开始节点只保留 3 个元数据变量：`order_no`（可空）、`agent_level`（new/veteran）、`scene_hint`（auto/产品/物流/政策/促销/投诉/技术/闲聊）
- 所有 LLM 节点 user 消息统一 `{{#sys.query#}}`
- 场景提示写进 system 消息里的变量引用，不再拼前缀、不再加模板节点

---

## 快捷路径（推荐）：直接导入改好的 DSL

`dify-workflow/kefu-copilot.yml` 已含全部改动（26 节点 / 31 边，YAML 校验通过）：

1. Dify → 工作室 → 创建空白应用 → 导入 DSL 文件 → 选 `dify-workflow/kefu-copilot.yml`。
   - 新建应用，**不要覆盖原应用**；v1 导入坏掉的那个可以删掉。
   - 导入后检查 6 个知识检索节点是否还挂在原知识库（同一工作区通常自动保留；若提示知识库不存在，重新选一次）。
2. 回到应用 → 访问 API → 复制**新应用的 API Key**。
3. 把新 Key 给我，或写进仓库 `.env` 的 `DIFY_APP_API_KEY`。
4. 跑 `python evaluation/run_copilot_eval.py --check-inputs`，3 个变量应全部 OK。
5. 按下面"知识库"一节补 4 个 txt（DSL 带不进数据集内容，必须手工导入）。

DSL 改动对照：

| 位置 | 改动 |
|---|---|
| 开始节点 | `order_no`（可选文本）、`agent_level`（下拉 new/veteran）、`scene_hint`（下拉 auto/产品/物流/政策/促销/投诉/技术/闲聊） |
| 8 个回答 LLM | system 换成 `prompts/copilot/*.md`；user 统一 `{{#sys.query#}}`；product/logistics 末尾追加库存/物流工具变量行；温度 0.2 |
| 问题分类 LLM | system 用 `intent.md`（内含场景提示变量），user `{{#sys.query#}}` |
| 兜底分支 | 原来写死的固定文案 → 新增「信息不足引导」LLM 节点（`unknown.md`）→ answer |
| 记忆配置 | 保持原样（`{{#sys.query#}}`），不动 |
| 意图路由 | if-else 结构不动；场景提示只影响提示词判断 |

如果导入后发现下拉变量没生效（个别版本对 select 支持有差异），把 `agent_level`、`scene_hint` 改成"文本"类型也能跑，评测脚本传的是字符串。

---

## 手工路径（不想重新导入时）

在已导入的 v1 应用上改 5 处：

1. 开始节点：删掉 `buyer_message`，保留 `order_no`/`agent_level`/`scene_hint`。
2. 8 个回答 LLM + 问题分类 LLM + 兜底 LLM：把 **user 消息**改成 `{{#sys.query#}}`（这一步就是解决报错）。
3. 删掉「场景提示拼接」模板节点，把"变量赋值"直接连回"问题分类"。
4. 问题分类的 system prompt 换成 `prompts/copilot/intent.md`。
5. 5 个知识检索、问题分类器的 query 若被改成 buyer_message，改回 `sys.query`。

## 知识库

把 `knowledge-base/copilot/` 下 4 个 txt 导入同一个 dataset：

- `01_policy_wording.txt`：能说什么/不能说什么
- `02_script_examples.txt`：好坏话术对照
- `03_escalation_rules.txt`：必须转主管的 10 种情形
- `04_uncertain_replies.txt`：不知道时的 6 个模板

检索参数：TopK 4，score 阈值 0.3。

## 跑评测

```powershell
python evaluation/run_copilot_eval.py --check-inputs      # 确认 3 个变量生效
python evaluation/run_copilot_eval.py --runs 1 --limit 5  # 冒烟 5 条
python evaluation/run_copilot_eval.py --runs 1            # 全量 30 条
```

报告写到 `evaluation/reports/copilot_eval/`，含逐条失败原因、按场景/按新老员工的分组通过率。

## 验收清单

- [ ] 开始节点 3 个变量存在，`--check-inputs` 全绿
- [ ] 任意消息返回合法 JSON，5 个字段齐全
- [ ] `agent_level=new` 时 `explanation` 非空，`veteran` 时为空
- [ ] 无订单号问物流 → `next_action=追问订单号`
- [ ] 提赔偿/315/差评 → `escalate=true`、`next_action=转主管`
- [ ] 政策题 `evidence` 能对应到知识库原文
- [ ] 新人/老员工同一问题的通过率差距可量化

## 常见坑

1. 变量名写成 `buyerMessage` 或 `buyer-message`，API 报 `inputs is invalid`。
2. LLM 节点 user 消息没引用 `sys.query`，编排校验直接报"user message 中必须包含sys.query"。
3. 知识检索 query 误用带前缀的拼接结果，检索命中率明显下降。
4. 温度没降，JSON 偶发多一句"好的，以下是回复"。
5. 兜底节点没改，unknown 场景返回纯文本，评测里 JSON 解析失败。
