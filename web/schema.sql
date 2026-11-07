-- 网页工作台 MVP 数据库（SQLite，试点够用；迁 Postgres 时改字段类型即可）

CREATE TABLE IF NOT EXISTS agents (
    agent_id     TEXT PRIMARY KEY,          -- 工号
    name         TEXT NOT NULL,
    password_hash TEXT NOT NULL,            -- pbkdf2_sha256$iterations$salt$hash
    level        TEXT NOT NULL DEFAULT 'veteran',  -- new / veteran
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL,
    agent_level      TEXT NOT NULL,
    scene_hint       TEXT,
    scene_detected   TEXT,
    order_no         TEXT,
    query            TEXT NOT NULL,
    reply            TEXT,
    evidence         TEXT,                  -- JSON 数组字符串
    next_action      TEXT,
    escalate         INTEGER,
    raw_answer       TEXT,
    latency_ms       INTEGER,
    dify_message_id  TEXT,
    status           TEXT NOT NULL DEFAULT 'pending', -- pending/copied/modified/useless/abandoned/failed
    final_text       TEXT,
    edit_distance    INTEGER,
    feedback_note    TEXT,
    useful           INTEGER,               -- 1/0/NULL
    session_started_at TEXT,
    session_ended_at   TEXT,
    aht_seconds      INTEGER,
    created_at       TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'web'    -- web / feishu
);

CREATE INDEX IF NOT EXISTS idx_conv_agent ON conversations(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status);

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id             TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    gap_type       TEXT NOT NULL,           -- no_kb / wrong_kb / outdated / wording / routing
    scene          TEXT,
    summary        TEXT NOT NULL,
    suggested_fix  TEXT,
    week           TEXT,                    -- 2026-W45
    status         TEXT NOT NULL DEFAULT 'open',
    created_at     TEXT NOT NULL
);
