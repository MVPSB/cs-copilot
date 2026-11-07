"""配置：从仓库根目录 .env 读取，web/.env 可覆盖。"""

from __future__ import annotations

import os
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent
ROOT = WEB_DIR.parent


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(ROOT / ".env")
load_dotenv(WEB_DIR / ".env")


class Config:
    dify_base: str = (os.getenv("DIFY_BASE_URL") or os.getenv("DIFY_API_BASE") or "http://localhost/v1").rstrip("/")
    dify_key: str = os.getenv("DIFY_APP_API_KEY", "")
    dify_timeout: int = int(os.getenv("DIFY_TIMEOUT", "60"))

    db_path: Path = Path(os.getenv("WEB_DB", str(WEB_DIR / "data" / "workbench.db")))
    secret: str = os.getenv("WEB_SECRET", "change-me-in-env")

    host: str = os.getenv("WEB_HOST", "127.0.0.1")
    port: int = int(os.getenv("WEB_PORT", "8100"))


config = Config()
