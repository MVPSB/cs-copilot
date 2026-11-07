# 客服副驾 · CS Copilot

> 电商客服的内部副驾：买家消息进来，把一版**可直接复制**的回复、**依据原文**和**下一步动作**放到客服面前。客服只做判断，不做检索。

面向速卖通/独立站一类"平台不开放第三方消息接口"的场景：机器人替不了买家回话，但可以替客服把"查政策、查物流、组织话术"这一步做完。

## 效果

同一套 200 条中文题库，单轮，任务解决率（pass@1）：

| 指标 | 数值 |
| --- | --- |
| 任务解决率（两轮合并） | **84.5%**（338/400），95% 区间 80.6%–87.6% |
| 单轮 | 85.0%（170/200）、84.0%（168/200） |
| 逐题两轮都过 | 78.5%（157/200） |
| P50 / P95 响应 | 8.9s / 12.4s |
| 线上试点（4 名客服、1 天） | 147 条会话，建议采纳率 **84.7%**，AHT 中位 17s |
| 试点问题回灌回归集 | 20/20 |

分场景（两轮合并）：产品 90%、促销 90%、未知 90%、政策 86%、投诉 85%、技术 77%、物流 70%、闲聊 100%。

口径说明：只报 pass@1（线上客服只有一次机会），每版至少两轮、报合并值，单轮只用于定位问题；"同集"表示题库参与过调参，泛化证据仍待留出集盲测。

## 架构

```
浏览器工作台 (web/static)
   │  工号密码登录
   ▼
网关 FastAPI (web/app)  ── SQLite：会话 / 采纳 / AHT / 知识缺口
   │  服务端持 Key、脱敏、限流
   ▼
Dify Chatflow (dify-workflow/kefu-copilot.yml)
   ├── 问题路由（8 个业务分支）
   ├── 知识库检索（9 份文档，混合检索 + 重排）
   └── MCP 工具：库存 :8000 / 物流 :8001
```

## 目录

```
prompts/copilot/      9 份提示词（路由 + 8 个业务分支），约束输出 JSON
knowledge-base/       9 份知识库文档（政策口径、话术范例、升级规则、短事实、促销、技术…）
dify-workflow/        Chatflow DSL 与构建/发布脚本
mcp-servers/          库存、物流两个 MCP 服务（mock 数据）
web/                  FastAPI 网关 + 三栏工作台（登录、生成、复制/修改/无用/放弃、周报）
evaluation/           200 条题库、评测脚本、Excel 导出、回归集
docs/                 评测报告、归因总表、MVP 复盘、规格与路线图
design/               设计 token 与界面截图
```

## 快速开始

```bash
# 1. 依赖
python -m pip install -r web/requirements.txt

# 2. 配置（.env 不会被提交）
cp .env.example .env
# 填 DIFY_BASE_URL / DIFY_APP_API_KEY

# 3. MCP 工具
python mcp-servers/stock_mcp_server.py       # :8000
python mcp-servers/logistics_mcp_server.py   # :8001

# 4. Dify：导入 dify-workflow/kefu-copilot.yml，上传 knowledge-base/ 下文档，发布后拿 API Key

# 5. 网关 + 工作台
cd web
python scripts/seed_accounts.py --reset      # 建 4 个试点账号
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

打开 http://127.0.0.1:8100 ，用工号密码登录。接口文档在 `/docs`。

## 评测

```bash
python evaluation/run_copilot_eval.py --testset evaluation/testset_copilot.json --out evaluation/reports/copilot_eval/local
python evaluation/summarize_200.py --report evaluation/reports/copilot_eval/local/latest.json
```

评测卡四件事：路由是否正确、必含/禁词、`next_action` 与 `escalate` 是否一致、依据是否为空。

## 数据与隐私

- 仓库内订单号、物流单号、商品均为 **mock 数据**；
- 网关在落库前对手机号、身份证、详细地址做脱敏，API Key 只存服务端环境变量；
- 详见 [PRIVACY.md](PRIVACY.md) 与 [SECURITY.md](SECURITY.md)。

## 已知限制

1. 物流、库存是 mock 服务，真实可用性要接 ERP 后再评估；
2. 200 条题库参与过调参，84.5% 带"同集"限定，留出集盲测还没做；
3. 题库全是单轮，追问、指代、多轮上下文未覆盖；
4. 判定是规则判定（必含词 + 动作 + 依据），不等于人工判定；
5. 场景下拉使用率低（131/147 是自动），分场景采纳率暂时只做参考。

## 文档

- [评测报告](docs/eval-report-final.md)：200 条口径、分场景、版本演进与失败归因
- [归因总表](docs/归因总表.md)：从改 Dify 到试点回灌的 23 个节点，现象 → 根因 → 解决 → 验证
- [MVP 复盘](docs/mvp-summary.md)：问题、交付、关键判断、下一步
- [架构说明](docs/architecture.md) / [工作台规格](docs/workbench-mvp-spec.md) / [上线路图](docs/roadmap-web-pilot.md)
