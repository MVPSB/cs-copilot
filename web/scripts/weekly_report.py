"""周报：用量、质量、知识缺口 Top10、下周动作；输出 md + xlsx。"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "weekly"

GAP_LABEL = {
    "no_kb": "知识库没有",
    "wrong_kb": "答错",
    "outdated": "内容过期",
    "wording": "话术不合适",
    "routing": "路由错误",
}


def week_bounds(offset: int = 0):
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    return monday, monday + timedelta(days=6)


def pct(value: int, total: int) -> str:
    return "—" if not total else f"{value / total * 100:.1f}%"


def collect(start: str, end: str) -> dict:
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM conversations WHERE date(created_at) BETWEEN ? AND ?", (start, end))]
        gaps = [dict(r) for r in conn.execute(
            "SELECT * FROM knowledge_gaps WHERE date(created_at) BETWEEN ? AND ?", (start, end))]
    return {"rows": rows, "gaps": gaps}


def summarize(rows: list[dict]) -> dict:
    decided = [r for r in rows if r["status"] in ("copied", "modified", "useless")]
    copied = sum(r["status"] == "copied" for r in decided)
    modified = sum(r["status"] == "modified" for r in decided)
    useless = sum(r["status"] == "useless" for r in decided)
    lat = sorted(r["latency_ms"] for r in rows if r["latency_ms"])
    aht = sorted(r["aht_seconds"] for r in rows if r["aht_seconds"] is not None and r["status"] != "abandoned")
    p50 = lat[len(lat) // 2] if lat else 0
    p95 = lat[min(len(lat) - 1, max(0, math.ceil(len(lat) * 0.95) - 1))] if lat else 0
    aht_med = aht[len(aht) // 2] if aht else 0
    by_scene = Counter(r["scene_hint"] for r in rows)
    return {
        "total": len(rows),
        "agents": len({r["agent_id"] for r in rows}),
        "decided": len(decided),
        "copied": copied,
        "modified": modified,
        "useless": useless,
        "adoption": pct(copied + modified, len(decided)),
        "edit_rate": pct(modified, copied + modified),
        "useless_rate": pct(useless, len(decided)),
        "p50": p50,
        "p95": p95,
        "aht": aht_med,
        "by_scene": by_scene.most_common(),
    }


def top_gaps(gaps: list[dict], limit: int = 10) -> list[dict]:
    merged: dict[tuple, dict] = {}
    for gap in gaps:
        key = (gap["gap_type"], gap["scene"])
        item = merged.setdefault(key, {"count": 0, "samples": []})
        item["count"] += 1
        if len(item["samples"]) < 3:
            item["samples"].append(gap["summary"])
    ordered = sorted(merged.items(), key=lambda kv: -kv[1]["count"])
    return [{"type": k[0], "scene": k[1], "count": v["count"], "samples": v["samples"]}
            for k, v in ordered[:limit]]


def write_markdown(summary: dict, gaps: list[dict], start: str, end: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    year, week, _ = date.fromisoformat(start).isocalendar()
    path = OUT_DIR / f"{year}-W{week:02d}.md"
    lines = [
        f"# 客服副驾周报 {year}-W{week:02d}（{start} ~ {end}）",
        "",
        "## 一、用量",
        f"- 会话数：{summary['total']}；活跃员工：{summary['agents']}；人均：{summary['total'] // max(summary['agents'], 1)} 次",
        f"- 模型耗时 P50 {summary['p50']} ms，P95 {summary['p95']} ms",
        f"- AHT 中位数：{summary['aht']} 秒（样本 {summary['decided']} 条）",
        "",
        "## 二、质量",
        f"- 采纳率 {summary['adoption']}（复制 {summary['copied']} + 修改后采纳 {summary['modified']}）",
        f"- 修改率 {summary['edit_rate']}；无用率 {summary['useless_rate']}",
        f"- 场景分布：{', '.join(f'{k} {v} 次' for k, v in summary['by_scene'])}",
        "",
        "## 三、知识缺口 Top 10",
    ]
    if not gaps:
        lines.append("- 本周无记录（员工未点“无用”或未填备注）")
    for i, gap in enumerate(gaps, 1):
        label = GAP_LABEL.get(gap["type"], gap["type"])
        lines.append(f"{i}. [{label} / {gap['scene'] or '未标注'}] {gap['count']} 条；样例：{gap['samples'][0]}")
    lines += ["", "## 四、下周动作", "- （人工填写，最多 3 条：谁、补哪份文档、什么时间）", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_xlsx(summary: dict, gaps: list[dict], start: str) -> Path:
    from openpyxl import Workbook

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    year, week, _ = date.fromisoformat(start).isocalendar()
    path = OUT_DIR / f"{year}-W{week:02d}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "指标"
    for row in [
        ("指标", "数值"),
        ("会话数", summary["total"]),
        ("活跃员工", summary["agents"]),
        ("采纳率", summary["adoption"]),
        ("修改率", summary["edit_rate"]),
        ("无用率", summary["useless_rate"]),
        ("P50 模型耗时(ms)", summary["p50"]),
        ("P95 模型耗时(ms)", summary["p95"]),
        ("AHT 中位数(秒)", summary["aht"]),
    ]:
        ws.append(row)
    gaps_ws = wb.create_sheet("知识缺口")
    gaps_ws.append(["类型", "场景", "条数", "样例"])
    for gap in gaps:
        gaps_ws.append([GAP_LABEL.get(gap["type"], gap["type"]), gap["scene"], gap["count"], "；".join(gap["samples"])])
    wb.save(path)
    return path


def main() -> None:
    offset = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    monday, sunday = week_bounds(offset)
    data = collect(monday.isoformat(), sunday.isoformat())
    summary = summarize(data["rows"])
    gaps = top_gaps(data["gaps"])
    md = write_markdown(summary, gaps, monday.isoformat(), sunday.isoformat())
    xlsx = write_xlsx(summary, gaps, monday.isoformat())
    print(f"已生成 {md}")
    print(f"已生成 {xlsx}")
    print(json.dumps(summary, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
