"""把 200 条评测集导出成可读的 Excel（含汇总页）。

用法：
    python evaluation/export_testset_xlsx.py
产出：
    evaluation/200条评测集.xlsx
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
TESTSET = ROOT / "evaluation" / "testset_copilot.json"
OUT = ROOT / "evaluation" / "200条评测集.xlsx"

HEADERS = ["编号", "场景", "员工", "场景提示", "订单号", "买家原话", "期望动作",
           "该升级", "必含词", "禁词", "要依据", "出题意图"]
WIDTHS = [6, 8, 8, 10, 18, 46, 14, 8, 24, 24, 8, 34]

SCENE_ORDER = ["产品", "物流", "政策", "促销", "投诉", "技术", "闲聊", "未知"]

HEAD_FILL = PatternFill("solid", fgColor="EFF4FF")
TITLE_FONT = Font(name="Microsoft YaHei", size=12, bold=True, color="1F2937")
HEAD_FONT = Font(name="Microsoft YaHei", size=10, bold=True, color="1F2937")
BODY_FONT = Font(name="Microsoft YaHei", size=10, color="374151")
THIN = Side(style="thin", color="E5E7EB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def join(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "、".join(str(v) for v in value)
    return str(value)


def main() -> None:
    cases = json.loads(TESTSET.read_text(encoding="utf-8"))
    wb = Workbook()

    ws = wb.active
    ws.title = "用例明细"
    for col, (head, width) in enumerate(zip(HEADERS, WIDTHS), start=1):
        cell = ws.cell(row=1, column=col, value=head)
        cell.font, cell.fill, cell.border = HEAD_FONT, HEAD_FILL, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:L{len(cases) + 1}"

    for row, case in enumerate(cases, start=2):
        values = [
            case.get("id"),
            case.get("scene"),
            "新人" if case.get("agent_level") == "new" else "老人",
            case.get("scene_hint") or "auto",
            case.get("order_no") or "",
            case.get("buyer_message", ""),
            join(case.get("expect_action") or case.get("expect_action_any")),
            {True: "是", False: "否", None: "不判"}.get(case.get("expect_escalate")),
            join(case.get("must_contain")),
            join(case.get("must_not_contain")),
            "要" if case.get("expect_evidence") else "不要",
            case.get("note", ""),
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font, cell.border = BODY_FONT, BORDER
            cell.alignment = Alignment(
                horizontal="center" if col in (1, 2, 3, 4, 7, 8, 11) else "left",
                vertical="top", wrap_text=True,
            )

    summary = wb.create_sheet("分布汇总")
    summary["A1"] = "200 条评测集分布"
    summary["A1"].font = TITLE_FONT
    headers = ["场景", "条数", "新人", "老人", "要依据", "该升级", "不该升级"]
    for col, head in enumerate(headers, start=1):
        cell = summary.cell(row=3, column=col, value=head)
        cell.font, cell.fill, cell.border = HEAD_FONT, HEAD_FILL, BORDER
        cell.alignment = Alignment(horizontal="center")
        summary.column_dimensions[get_column_letter(col)].width = 12

    rows = []
    for scene in SCENE_ORDER:
        subset = [c for c in cases if c.get("scene") == scene]
        if not subset:
            continue
        rows.append([
            scene,
            len(subset),
            sum(c.get("agent_level") == "new" for c in subset),
            sum(c.get("agent_level") == "veteran" for c in subset),
            sum(bool(c.get("expect_evidence")) for c in subset),
            sum(c.get("expect_escalate") is True for c in subset),
            sum(c.get("expect_escalate") is False for c in subset),
        ])
    total = ["合计", len(cases),
             sum(r[2] for r in rows), sum(r[3] for r in rows),
             sum(r[4] for r in rows), sum(r[5] for r in rows), sum(r[6] for r in rows)]
    for idx, values in enumerate(rows + [total], start=4):
        for col, value in enumerate(values, start=1):
            cell = summary.cell(row=idx, column=col, value=value)
            cell.font = Font(name="Microsoft YaHei", size=10, bold=(values[0] == "合计"))
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="center")

    note = summary["A15"]
    note.value = "每条的判定 = 路由正确 + 必含/禁词通过 + 动作符合 + 该升级时升级（不判的条目跳过）+ 依据非空"
    note.font = Font(name="Microsoft YaHei", size=9, color="6B7280")

    wb.save(OUT)
    print("written", OUT, "cases=", len(cases))
    print("scenes:", dict(Counter(c.get("scene") for c in cases)))


if __name__ == "__main__":
    main()
