#!/usr/bin/env python3
"""把对外客服版 DSL 改写成内部副驾版 DSL（v2）。

输入: dify-workflow/kefu-current.yml
输出: dify-workflow/kefu-copilot.yml

v2 与 v1 的差别：Dify 校验要求 LLM 节点的 user 消息必须引用 sys.query
（否则报"user message 中必须包含 sys.query"）。所以 v2 不再把买家原话塞进
buyer_message 变量，而是：
  - 买家原话 = 对话输入 sys.query（员工在聊天框里粘贴）
  - 开始节点只保留 order_no / agent_level / scene_hint 三个元数据变量
  - 所有 LLM 节点 user 消息统一为 {{#sys.query#}}
  - 场景提示改为写进 system 消息里的变量引用，不再拼前缀、不再加模板节点

改动清单:
1. 开始节点: order_no / agent_level / scene_hint（无 buyer_message）
2. 9 个 LLM 节点 system 换成 prompts/copilot/*.md，user 统一 {{#sys.query#}}，温度 0.2
3. 新增「信息不足引导」LLM 节点，替换原来写死的兜底文案
4. 记忆配置（memory）保持原样，不动
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dify-workflow" / "kefu-current.yml"
DST = ROOT / "dify-workflow" / "kefu-copilot.yml"
PROMPT_DIR = ROOT / "prompts" / "copilot"

START_ID = "1789562177817"
IFELSE_ID = "1789563096751"
ANSWER_ID = "1790779672607"
UNKNOWN_LLM_ID = "1789900000002"
CLEAN_ID = "1789900000011"
ASSIGNER_ID = "1789563091120"
INTENT_ID = "1789563120831"

LLM_PROMPTS = {
    "1789563120831": "intent.md",      # 问题分类
    "1789721830758": "chitchat.md",    # 闲聊回答
    "1789721922630": "promotion.md",   # 促销活动回答
    "1789721925966": "tech.md",        # 技术支持回答
    "1789721929703": "complaint.md",   # 投诉回答
    "1789731569091": "product.md",     # 产品咨询回答
    "1789731645578": "logistics.md",   # 物流咨询回答
    "1789735390944": "policy.md",      # 店铺政策咨询回答
}

TOOL_LINES = {
    "1789731569091": "【库存查询结果】{{#1789731455298.text#}}{{#1789731455298.result#}}",
    "1789731645578": "【物流查询结果】{{#1789731640234.text#}}",
}

PLACEHOLDERS = {
    "{{#order_no#}}": f"{{{{#{START_ID}.order_no#}}}}",
    "{{#agent_level#}}": f"{{{{#{START_ID}.agent_level#}}}}",
    "{{#scene_hint#}}": f"{{{{#{START_ID}.scene_hint#}}}}",
}


def read_prompt(name: str) -> str:
    """读提示词，去掉“买家原话”行（原话由 user 消息 sys.query 提供），替换变量占位符。"""
    lines = (PROMPT_DIR / name).read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if "{{#buyer_message#}}" not in line]
    text = "\n".join(kept).strip()
    for old, new in PLACEHOLDERS.items():
        text = text.replace(old, new)
    return text


def edge(source: str, target: str, source_type: str, target_type: str, handle: str = "source") -> dict:
    return {
        "data": {
            "isInIteration": False,
            "isInLoop": False,
            "iteration_id": None,
            "loop_id": None,
            "sourceType": source_type,
            "targetType": target_type,
        },
        "id": f"{source}-source-{target}-target",
        "selected": False,
        "source": source,
        "sourceHandle": handle,
        "target": target,
        "targetHandle": "target",
        "type": "custom",
        "zIndex": 0,
    }


def node_wrap(node_id: str, data: dict, x: float, y: float, width: int = 242) -> dict:
    return {
        "height": 100,
        "id": node_id,
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "type": "custom",
        "width": width,
        "zIndex": 0,
        "data": data,
    }


def main() -> None:
    doc = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    graph = doc["workflow"]["graph"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = graph["edges"]

    # 1. 开始节点变量：只保留元数据，买家原话走 sys.query
    nodes[START_ID]["data"]["variables"] = [
        {"variable": "order_no", "label": "订单号（可空）", "type": "text-input", "required": False, "max_length": 64, "options": []},
        {"variable": "agent_level", "label": "员工经验", "type": "select", "required": True, "options": ["new", "veteran"]},
        {"variable": "scene_hint", "label": "场景提示", "type": "select", "required": True,
         "options": ["auto", "产品", "物流", "政策", "促销", "投诉", "技术", "闲聊"]},
    ]

    # 2. 温度统一 0.2；按节点设置输出上限，防止 JSON 被截断
    MAX_TOKENS = {"问题分类": 200, "信息不足引导": 800}
    for node in nodes.values():
        data = node["data"]
        if isinstance(data.get("model"), dict) and data["model"].get("completion_params"):
            params = data["model"]["completion_params"]
            params["temperature"] = 0.2
            params["max_tokens"] = MAX_TOKENS.get(data.get("title"), 3000)

    # 2.5 用 prompts/copilot/*.md 覆盖各回答节点的 system 提示词（导入时被 Kefu 原始提示词占位）
    for node in graph["nodes"]:
        prompt_name = LLM_PROMPTS.get(node["id"])
        if not prompt_name:
            continue
        tmpl = node["data"].get("prompt_template") or []
        if tmpl:
            text = read_prompt(prompt_name)
            tool_line = TOOL_LINES.get(node["id"], "")
            if tool_line:
                text = text + "\n\n" + tool_line
            tmpl[0]["text"] = text

    # 3. 新增「信息不足引导」LLM 节点，替换写死的兜底 answer
    unknown_data = {
        "type": "llm",
        "context": {"enabled": False, "variable_selector": []},
        "model": {
            "completion_params": {"temperature": 0.2, "max_tokens": 800},
            "mode": "chat",
            "name": "deepseek-v4-flash",
            "provider": "langgenius/deepseek/deepseek",
        },
        "prompt_template": [
            {"role": "system", "text": read_prompt("unknown.md")},
            {"role": "user", "text": "{{#sys.query#}}"},
        ],
        "selected": False,
    }
    clean_data = {
        "type": "template-transform",
        "title": "\u68c0\u7d22\u8bcd\u6e05\u6d17",
        "variables": [{"variable": "query", "value_selector": [START_ID, "sys.query"]}],
        "template": "{{ query.rstrip('\uff1f?\u3002\uff01!\uff0c,\u3001 ') }}",
    }

    graph["nodes"].append(node_wrap(CLEAN_ID, clean_data, 320, 120))
    for item in edges:
        if item["source"] == ASSIGNER_ID and item["target"] == INTENT_ID:
            item["target"] = CLEAN_ID
            item["id"] = f"{ASSIGNER_ID}-source-{CLEAN_ID}-target"
            item["data"]["targetType"] = "template-transform"
    edges.append(edge(CLEAN_ID, INTENT_ID, "template-transform", "llm"))
    for node in graph["nodes"]:
        if node["data"].get("type") == "knowledge-retrieval":
            # Dify 的检索节点字段名是 query_variable_selector；写成 query 会被忽略。
            node["data"].pop("query", None)
            node["data"]["query_variable_selector"] = [CLEAN_ID, "output"]

    # 6. v3.5：订单号提取器改为直接读开始节点的 order_no 变量
    #    之前它只看 sys.query（买家原话），测试集把单号放在 order_no 输入里，导致工具查不到。
    extractor = nodes["1790773251927"]["data"]
    extractor["query"] = ["1789562177817", "order_no"]
    extractor["instruction"] = (
        "输入是员工填写的订单号或运单号（可能为「未知」或空）。\n"
        "规则：\n"
        "1. 输入里是 HP 开头的订单号或 SF/JD/DB/ZT/YT 开头的运单号，原样输出该编号。\n"
        "2. 输入为空、未知、或不是编号，输出「未知」。\n"
        "3. 只输出编号或「未知」，不要解释。\n"
    )

    # 6.5 v3.10：供应商与重排修正。
    #   a) 意图分类节点还挂在 siliconflow 的 DeepSeek-V4-Flash 上，该模型在账号侧已 disabled（403 Model disabled），
    #      统一改到 deepseek 官方供应商，和其它回答节点一致。
    #   b) 6 个检索节点用 siliconflow 的 bce/Qwen 重排模型，实测 403 后检索返回 0 条（“知识库为空”），
    #      关掉重排、退回混合检索（0.7 向量 + 0.3 关键词），不依赖第三方重排服务。
    for node in graph["nodes"]:
        ntype = node["data"].get("type")
        if ntype in ("llm", "question-classifier", "parameter-extractor"):
            # 分类器和参数提取器也带 model 字段，同样必须迁到 deepseek，否则仍会打 siliconflow（连接超时/403）。
            model = node["data"].setdefault("model", {})
            model["provider"] = "langgenius/deepseek/deepseek"
            model["name"] = "deepseek-v4-flash"
            model["mode"] = model.get("mode") or "chat"
        elif ntype == "knowledge-retrieval":
            cfg = node["data"].setdefault("multiple_retrieval_config", {})
            # v4.8：bge-reranker-v2-m3 实测可用（dataset API 打分 0.949），混合召回 20 条再重排取 8 条。
            cfg["reranking_enable"] = True
            cfg["reranking_mode"] = "reranking_model"
            cfg["reranking_model"] = {
                "reranking_provider_name": "langgenius/siliconflow/siliconflow",
                "reranking_model_name": "BAAI/bge-reranker-v2-m3",
            }
            cfg["weights"] = {
                "weight_type": "customized",
                "vector_setting": {"vector_weight": 0.7, "embedding_provider_name": "", "embedding_model_name": ""},
                "keyword_setting": {"keyword_weight": 0.3},
            }
            cfg["score_threshold"] = None
            cfg["top_k"] = 8

    # 6.6 v3.10：知识库 dataset_id 显式写成 UUID。
    #    导出的 DSL 里 dataset_ids 是一串编码值（2dPGxb7Ct...），UI 导入时会自动解析，
    #    但我们直接改库/重导时必须给真实 UUID，否则检索报 invalid input syntax for type uuid。
    DATASET_ID = "7e0f827c-62ce-422a-912e-447e252ceaa5"
    for node in graph["nodes"]:
        if node["data"].get("type") == "knowledge-retrieval":
            node["data"]["dataset_ids"] = [DATASET_ID]

    # 3.5 兜底分支改走「信息不足引导」LLM，answer 节点引用它的 text
    graph["nodes"].append(node_wrap(UNKNOWN_LLM_ID, unknown_data, 320, 260))
    for item in edges:
        if item["source"] == IFELSE_ID and item["target"] == ANSWER_ID:
            item["target"] = UNKNOWN_LLM_ID
            item["id"] = f"{IFELSE_ID}-source-{UNKNOWN_LLM_ID}-target"
            item["data"]["targetType"] = "llm"
    edges.append(edge(UNKNOWN_LLM_ID, ANSWER_ID, "llm", "answer"))
    # 条件全不命中时 Dify 走 false 句柄；没有这条边流程会停住、返回空回答。
    edges.append(edge(IFELSE_ID, UNKNOWN_LLM_ID, "if-else", "llm", handle="false"))
    nodes[ANSWER_ID]["data"]["variables"] = [
        {"variable": "text", "value_selector": [UNKNOWN_LLM_ID, "text"]}
    ]
    nodes[ANSWER_ID]["data"]["answer"] = "{{#%s.text#}}" % UNKNOWN_LLM_ID

    FORMAT_SUFFIX = (
        "\n\n【输出格式】只输出一个 JSON 对象，不要输出思考过程，不要加代码块标记。字段与取值如下：\n"
        "{\n"
        '  "reply": "中文话术，不超过 200 字，可直接复制发给买家",\n'
        '  "evidence": ["从知识库原文摘录的短句，最多 3 条；没有依据时填空数组 []"],\n'
        '  "explanation": "新人填写：一句话说明为什么这么说；老员工填空字符串 \\"\\"",\n'
        '  "next_action": "只能取：直接回复 / 追问订单号 / 追问产品 / 查库存 / 查物流 / 转主管",\n'
        '  "escalate": false\n'
        "}\n"
        "【字段一致】next_action 为「转主管」时 escalate 必须为 true，其余情况必须为 false。\n"
        "【explanation 规则】agent_level=veteran 时 explanation 必须是空字符串 \"\"；agent_level=new 时必须写一句为什么。\n"
        "【reply 禁词】reply 里绝对不能出现“知识库”“检索”“根据文档”这类内部词。\n"
        "【动作边界】只有这六类才 next_action=转主管、escalate=true：索赔/赔偿、退款金额争议、政策例外、客户坚持追责或要投诉到平台、少件/破损/错发需要补发退款、金额≥500 的补偿。\n"
        "价格、参数、库存、活动规则、发票、包邮、时效、退货地址、保修范围这类问题，一律 next_action=直接回复、escalate=false。\n"
        "知识库没有明确条款时：先按通用口径回答并建议核实，不要直接转主管；只有涉及赔付或例外才转。\n"
        "追问产品只在“答案必须依赖具体型号且买家没给型号”时使用；买家给了型号、或问的是品类通用信息，直接回复。\n"
        "escalate=true 时 reply 里必须出现“主管”二字；escalate=false 时 reply 里不要出现“主管”。\n"
    )
    for node in graph["nodes"]:
        if node["data"].get("type") == "llm":
            tmpl = node["data"].get("prompt_template") or []
            if tmpl and "【输出格式】" not in tmpl[0].get("text", ""):
                tmpl[0]["text"] = tmpl[0].get("text", "") + FORMAT_SUFFIX

    # 7. 校验
    assert len(graph["nodes"]) == 27, len(graph["nodes"])
    assert nodes[START_ID]["data"]["variables"][0]["variable"] == "order_no"

    DST.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False, width=10000),
        encoding="utf-8",
    )
    print(f"written {DST} nodes={len(graph['nodes'])} edges={len(edges)}")


if __name__ == "__main__":
    main()
