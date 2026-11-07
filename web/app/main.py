"""网页工作台网关：登录、生成建议、记录结果、反馈、探活。"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import config
from .db import connect, init_db
from .dify import DifyError, call_dify
from .pii import mask_pii
from .security import issue_token, read_token, verify_password

app = FastAPI(title="客服副驾工作台网关", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# 超过这个时长的会话视为“中途离开”，AHT 按上限截断（10 分钟）
MAX_AHT_SECONDS = 600
# 从聚焦输入框算起的“会话时长”上限（避免长时间挂着，60 分钟）
MAX_FOCUS_SECONDS = 3600
# 超过这个时长仍未标记的会话，下一条提问时自动标记为 abandoned（10 分钟）
PENDING_EXPIRE_SECONDS = 600


def _iso_minus(seconds: int) -> str:
    return (datetime.now(timezone.utc).astimezone() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def require_agent(authorization: str = Header(default="")) -> dict:
    token = authorization.replace("Bearer ", "").strip()
    agent_id = read_token(token) if token else None
    if not agent_id:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    with connect() as conn:
        row = conn.execute("SELECT agent_id, name, level FROM agents WHERE agent_id=? AND active=1", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="账号不存在或已停用")
    return dict(row)


class LoginIn(BaseModel):
    agent_id: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AskIn(BaseModel):
    buyer_message: str = Field(min_length=1)
    order_no: str = ""
    agent_level: Literal["new", "veteran"] = "veteran"
    scene_hint: str = "auto"
    started_at: str | None = None


class ResultIn(BaseModel):
    conversation_id: str
    status: Literal["copied", "modified", "useless", "abandoned"]
    final_text: str = ""
    note: str = ""
    ended_at: str | None = None


class FeedbackIn(BaseModel):
    conversation_id: str
    useful: bool
    note: str = ""


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "time": now_iso(), "db": str(config.db_path)}


@app.post("/api/login")
def login(body: LoginIn) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM agents WHERE agent_id=? AND active=1", (body.agent_id,)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="工号或密码错误")
    return {"token": issue_token(row["agent_id"]), "agent_id": row["agent_id"], "name": row["name"], "level": row["level"]}


@app.get("/api/me")
def me(agent: dict = Depends(require_agent)) -> dict:
    return agent


SCENE_ALIASES = {
    "产品咨询": "产品",
    "物流咨询": "物流",
    "政策咨询": "政策",
    "促销活动": "促销",
    "投诉处理": "投诉",
    "技术支持": "技术",
    "闲聊": "闲聊",
    "未知": "未知",
}


def normalize_scene(value: str) -> str:
    return SCENE_ALIASES.get(value, value or "auto")


@app.post("/api/ask")
def ask(body: AskIn, agent: dict = Depends(require_agent)) -> dict:
    started_at = body.started_at or now_iso()
    scene_hint = normalize_scene(body.scene_hint)
    # 客服常把订单号直接粘在买家原话里、订单号输入框留空，这里兜底提取一次
    order_no = body.order_no.strip()
    if not order_no:
        matched = re.search(r"\b([A-Z]{2}\d{10,14})\b", body.buyer_message.upper())
        if matched:
            order_no = matched.group(1)
    # 上一个建议如果 10 分钟还没被标记，视为已放弃，避免 pending 堆积
    with connect() as conn:
        conn.execute(
            "UPDATE conversations SET status='abandoned', session_ended_at=?"
            " WHERE agent_id=? AND status='pending' AND created_at < ?",
            (now_iso(), agent["agent_id"], _iso_minus(PENDING_EXPIRE_SECONDS)),
        )
        conn.commit()
    t0 = time.perf_counter()
    try:
        result = call_dify(body.buyer_message, order_no, body.agent_level, scene_hint, agent["agent_id"])
    except DifyError as exc:
        latency = int((time.perf_counter() - t0) * 1000)
        conv_id = str(uuid.uuid4())
        with connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, agent_id, agent_level, scene_hint, order_no, query, latency_ms, status,"
                " session_started_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (conv_id, agent["agent_id"], body.agent_level, scene_hint, body.order_no,
                 mask_pii(body.buyer_message), latency, "failed", started_at, now_iso()),
            )
            conn.commit()
        raise HTTPException(status_code=502, detail={"message": str(exc), "conversation_id": conv_id})

    latency = int((time.perf_counter() - t0) * 1000)
    conv_id = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, agent_id, agent_level, scene_hint, order_no, query, reply, evidence,"
            " next_action, escalate, raw_answer, latency_ms, dify_message_id, status, session_started_at, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (conv_id, agent["agent_id"], body.agent_level, scene_hint, body.order_no,
             mask_pii(body.buyer_message), mask_pii(result["reply"]), json.dumps(result["evidence"], ensure_ascii=False),
             result["next_action"], int(result["escalate"]), result["raw_answer"], latency,
             result["message_id"], "pending", started_at, now_iso()),
        )
        conn.commit()
    return {
        "conversation_id": conv_id,
        "reply": result["reply"],
        "evidence": result["evidence"],
        "next_action": result["next_action"],
        "escalate": result["escalate"],
        "explanation": result["explanation"],
        "latency_ms": latency,
        "resources": result["resources"],
    }


@app.post("/api/result")
def record_result(body: ResultIn, agent: dict = Depends(require_agent)) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (body.conversation_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="会话不存在")
        if row["agent_id"] != agent["agent_id"]:
            raise HTTPException(status_code=403, detail="不能修改他人会话")
        final_text = mask_pii(body.final_text or row["reply"] or "")
        edit_distance = _edit_distance(row["reply"] or "", final_text) if body.status == "modified" else 0
        ended_at = body.ended_at or now_iso()
        # AHT 采用“提交建议 → 标记结果”的口径：只算拿到建议后的判断/编辑时间，
        # 避免客服把输入框放着不管产生的空闲时间混进 AHT。
        aht = _seconds_between(row["created_at"], ended_at)
        focus_seconds = _seconds_between(row["session_started_at"], ended_at)
        if aht is not None and aht > MAX_AHT_SECONDS:
            aht = MAX_AHT_SECONDS
        if focus_seconds is not None and focus_seconds > MAX_FOCUS_SECONDS:
            focus_seconds = MAX_FOCUS_SECONDS
        conn.execute(
            "UPDATE conversations SET status=?, final_text=?, edit_distance=?, feedback_note=?, session_ended_at=?,"
            " aht_seconds=?, focus_seconds=? WHERE id=?",
            (body.status, final_text, edit_distance, body.note, ended_at, aht, focus_seconds, body.conversation_id),
        )
        if body.status in ("useless", "modified") and body.note:
            _maybe_gap(conn, row, body.status, body.note, final_text)
        conn.commit()
    return {"ok": True, "aht_seconds": aht, "edit_distance": edit_distance}


@app.post("/api/feedback")
def feedback(body: FeedbackIn, agent: dict = Depends(require_agent)) -> dict:
    with connect() as conn:
        conn.execute("UPDATE conversations SET useful=?, feedback_note=COALESCE(NULLIF(?, ''), feedback_note) WHERE id=? AND agent_id=?",
                     (int(body.useful), body.note, body.conversation_id, agent["agent_id"]))
        conn.commit()
    return {"ok": True}


def _seconds_between(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    except ValueError:
        return None


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


GAP_KEYWORDS = {
    "no_kb": ("没有", "查不到", "没写", "未覆盖", "没有这条"),
    "wrong_kb": ("答错", "不对", "错了", "错"),
    "outdated": ("过期", "旧", "变了", "已经改"),
    "wording": ("语气", "话术", "太硬", "啰嗦", "不像"),
}


def _maybe_gap(conn, row, status: str, note: str, final_text: str) -> None:
    gap_type = "no_kb"
    for kind, words in GAP_KEYWORDS.items():
        if any(w in note for w in words):
            gap_type = kind
            break
    if status == "modified" and gap_type == "no_kb":
        gap_type = "wording"
    week = datetime.now().isocalendar()
    conn.execute(
        "INSERT INTO knowledge_gaps (id, conversation_id, gap_type, scene, summary, suggested_fix, week, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), row["id"], gap_type, row["scene_hint"], f"{row['query'][:40]}：{note[:60]}",
         final_text[:120], f"{week.year}-W{week.week:02d}", now_iso()),
    )

class BeaconIn(BaseModel):
    token: str
    conversation_id: str
    status: Literal["abandoned", "copied", "modified", "useless"] = "abandoned"
    final_text: str = ""
    note: str = ""
    ended_at: str | None = None


@app.post("/api/beacon")
def beacon(body: BeaconIn) -> dict:
    """页面关闭/切走时的兜底上报：sendBeacon 不能带 Authorization 头，token 放 body。"""
    agent_id = read_token(body.token)
    if not agent_id:
        return {"ok": False}
    with connect() as conn:
        row = conn.execute("SELECT agent_id, name, level FROM agents WHERE agent_id=? AND active=1", (agent_id,)).fetchone()
    if not row:
        return {"ok": False}
    try:
        record_result(ResultIn(**body.model_dump(exclude={"token"})), dict(row))
    except HTTPException:
        return {"ok": False}
    return {"ok": True}


@app.get("/api/stats")
def stats(days: int = 7, agent: dict = Depends(require_agent)) -> dict:
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM conversations WHERE created_at>=?", (since,)).fetchall()]
        gaps = [dict(r) for r in conn.execute("SELECT gap_type, summary FROM knowledge_gaps WHERE created_at>=?", (since,)).fetchall()]

    def pct(part: int, whole: int) -> float:
        return round(part * 100 / whole, 1) if whole else 0.0

    total = len(rows)
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    # 采纳/无用只在“已判定”的会话里算：未标记（pending）和放弃（abandoned）不进分母，
    # 否则客服点完就走会凭空拉低采纳率。
    decided = by_status.get("copied", 0) + by_status.get("modified", 0) + by_status.get("useless", 0)
    adopted = by_status.get("copied", 0) + by_status.get("modified", 0)
    ahts = sorted([r["aht_seconds"] for r in rows if r["aht_seconds"]])
    scenes, levels = {}, {}
    for r in rows:
        if r["status"] not in ("copied", "modified", "useless"):
            continue
        s = scenes.setdefault(r["scene_hint"] or "未知", {"total": 0, "adopted": 0})
        s["total"] += 1
        if r["status"] in ("copied", "modified"):
            s["adopted"] += 1
        lv = levels.setdefault(r["agent_level"], {"total": 0, "adopted": 0})
        lv["total"] += 1
        if r["status"] in ("copied", "modified"):
            lv["adopted"] += 1
    gap_counts = {}
    for g in gaps:
        gap_counts[g["gap_type"]] = gap_counts.get(g["gap_type"], 0) + 1
    return {
        "days": days,
        "total": total,
        "decided": decided,
        "by_status": by_status,
        "adoption_rate": pct(adopted, decided),
        "copy_rate": pct(by_status.get("copied", 0), decided),
        "edit_rate": pct(by_status.get("modified", 0), decided),
        "useless_rate": pct(by_status.get("useless", 0), decided),
        "abandoned_rate": pct(by_status.get("abandoned", 0), total),
        "pending_rate": pct(by_status.get("pending", 0), total),
        "aht_p50": ahts[len(ahts) // 2] if ahts else None,
        "aht_mean": round(sum(ahts) / len(ahts), 1) if ahts else None,
        "latency_p50": sorted([r["latency_ms"] for r in rows if r["latency_ms"]])[len(rows) // 2] if rows else None,
        "by_scene": scenes,
        "by_level": levels,
        "gaps": gap_counts,
        "gap_examples": [g["summary"] for g in gaps[:5]],
    }


# 静态页面（放在所有 /api 路由之后挂载，避免吃掉接口）
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
