"""把 dify-workflow/kefu-copilot.yml 直接发布成 Dify 应用的新版本（绕过 GUI 导入）。

用法：python evaluation/publish_dsl.py [--app 1fc84538-846e-43bc-b936-e5ba85295f9a]
"""
import argparse
import json
import subprocess
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "1fc84538-846e-43bc-b936-e5ba85295f9a"


def psql(sql: str, db: bool = True) -> str:
    out = subprocess.run(
        ["docker", "exec", "docker-db_postgres-1", "psql", "-U", "postgres", "-d", "dify", "-t", "-A", "-c", sql],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise SystemExit(out.stderr)
    return out.stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=APP_ID)
    ap.add_argument("--dsl", default=str(ROOT / "dify-workflow" / "kefu-copilot.yml"))
    args = ap.parse_args()

    dsl = yaml.safe_load(Path(args.dsl).read_text(encoding="utf-8"))
    graph = {"nodes": dsl["workflow"]["graph"]["nodes"], "edges": dsl["workflow"]["graph"]["edges"]}
    tmp = ROOT / "dify-workflow" / "_graph_publish.json"
    tmp.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")

    subprocess.run(["docker", "cp", str(tmp), "docker-db_postgres-1:/tmp/graph_publish.json"], check=True)

    wf = psql(f"SELECT workflow_id FROM apps WHERE id='{args.app}';")
    ver = int(psql(f"SELECT version_number FROM workflows WHERE id='{wf}';"))
    new_id = str(uuid.uuid4())

    sql = f"""
BEGIN;
INSERT INTO workflows (id, tenant_id, app_id, type, version, graph, features, created_by, created_at,
                       updated_by, updated_at, environment_variables, conversation_variables,
                       marked_name, marked_comment, version_number)
SELECT '{new_id}', tenant_id, app_id, type, 'draft-{new_id[:8]}', :'g'::jsonb, features,
       created_by, now(), updated_by, now(), environment_variables, conversation_variables,
       '', '', {ver + 1}
FROM workflows WHERE id = '{wf}';
UPDATE apps SET workflow_id = '{new_id}', updated_at = now() WHERE id = '{args.app}';
COMMIT;
"""
    sql_file = ROOT / "dify-workflow" / "_publish.sql"
    sql_file.write_text(sql, encoding="utf-8")
    subprocess.run(["docker", "cp", str(sql_file), "docker-db_postgres-1:/tmp/publish.sql"], check=True)
    out = subprocess.run(
        ["docker", "exec", "docker-db_postgres-1", "psql", "-U", "postgres", "-d", "dify",
         "-c", "\\set g `cat /tmp/graph_publish.json`", "-f", "/tmp/publish.sql"],
        capture_output=True, text=True, encoding="utf-8",
    )
    print(out.stdout[-400:], out.stderr[-300:])
    print("published", new_id, "version", ver + 1)


if __name__ == "__main__":
    main()
