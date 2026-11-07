"""调用 Dify：只发三个业务输入变量，解析结构化 JSON。"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid

from .config import config


class DifyError(RuntimeError):
    pass


def _strip_reasoning(text: str) -> str:
    return re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.S).strip()


def _parse_json(text: str) -> dict:
    text = _strip_reasoning(text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise DifyError("回答不是合法 JSON")
    candidate = text[start:end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise DifyError(f"回答不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DifyError("回答不是 JSON 对象")
    return data


def call_dify(buyer_message: str, order_no: str, agent_level: str, scene_hint: str, user: str) -> dict:
    if not config.dify_key:
        raise DifyError("未配置 DIFY_APP_API_KEY")

    payload = {
        "inputs": {
            "order_no": order_no or "",
            "agent_level": agent_level,
            "scene_hint": scene_hint or "auto",
        },
        "query": buyer_message,
        "response_mode": "blocking",
        "user": user,
        "conversation_id": "",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{config.dify_base}/chat-messages",
        data=body,
        headers={"Authorization": f"Bearer {config.dify_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.dify_timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise DifyError(f"Dify HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise DifyError(f"Dify 不可达: {exc.reason}") from exc

    answer = _parse_json(data.get("answer", ""))
    return {
        "reply": answer.get("reply", ""),
        "evidence": answer.get("evidence", []),
        "next_action": answer.get("next_action", ""),
        "escalate": bool(answer.get("escalate", False)),
        "explanation": answer.get("explanation", ""),
        "message_id": data.get("message_id") or str(uuid.uuid4()),
        "raw_answer": data.get("answer", ""),
        "resources": [
            {"document_name": r.get("document_name"), "score": r.get("score")}
            for r in (data.get("metadata") or {}).get("retriever_resources", [])
        ],
    }
