"""初始化 4 个试点账号并打印初始密码。

用法：
    python scripts/seed_accounts.py            # 只补缺失账号
    python scripts/seed_accounts.py --reset    # 清空 agents 表重新建（不动会话数据）
"""

from __future__ import annotations

import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect, init_db  # noqa: E402
from app.security import hash_password  # noqa: E402

# 工号, 姓名, 角色
ACCOUNTS = [
    ("A1001", "郑（新人）", "new"),
    ("A1002", "王（新人）", "new"),
    ("A1003", "林（老人）", "veteran"),
    ("A1004", "李（老人）", "veteran"),
]


def main() -> None:
    reset = "--reset" in sys.argv
    init_db()
    created = []
    with connect() as conn:
        if reset:
            conn.execute("DELETE FROM agents")
        for agent_id, name, level in ACCOUNTS:
            exists = conn.execute("SELECT 1 FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            if exists:
                conn.execute("UPDATE agents SET name=?, level=?, active=1 WHERE agent_id=?", (name, level, agent_id))
                continue
            password = f"Kf-{secrets.token_urlsafe(6)}"
            conn.execute(
                "INSERT INTO agents (agent_id, name, password_hash, level, active, created_at) VALUES (?,?,?,?,1,?)",
                (agent_id, name, hash_password(password), level,
                 datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")),
            )
            created.append((agent_id, name, level, password))
        conn.commit()

    if not created:
        print("没有新建账号（已存在则只更新了姓名与角色）。")
        return
    print("已创建账号（密码只显示这一次，请保存好）：")
    for agent_id, name, level, password in created:
        print(f"  工号={agent_id}  姓名={name}  角色={level}  初始密码={password}")


if __name__ == "__main__":
    main()
