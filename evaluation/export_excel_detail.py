#!/usr/bin/env python3
"""导出 60 条评测结果（含完整回答）：汇总 / 明细 / 失败 / 回答全文 / 原始输出 / 说明。"""

import argparse
import json
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evaluation" / "reports" / "copilot_eval" / "latest.json"
TESTSET = ROOT / "evaluation" / "testset_copilot.json"
OUT = ROOT / "evaluation" / "reports" / "copilot_eval" / "60条评测结果_详细回答.xlsx"

SCENE_CN = {
    "product": "产品", "logistics": "物流", "policy": "政策", "promotion": "促销",
    "complaint": "投诉", "tech": "技术", "chitchat": "闲聊", "unknown": "未知",
}
LEVEL_CN = {"new": "新人", "veteran": "老员工"}

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
PASS_FILL = PatternFill("solid", fgColor="E2EFDA")
FAIL_FILL = PatternFill("solid", fgColor="FCE4E4")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="top", wrap_text=True)


def clean_answer(answer: str) -> dict:
    text = re.sub(r"<think>.*?(?:</think>|$)", "", answer or "", flags=re.S).strip()
    start = text.find("{")
    if start == -1:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def header(ws, row: int, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = CENTER
        cell.border = BORDER


def write_table(ws, headers, widths, rows, center_cols):
    for i, (h, w) in enumerate(zip(headers, widths), start=1):
        ws.cell(row=1, column=i, value=h)
        ws.column_dimensions[get_column_letter(i)].width = w
    header(ws, 1, len(headers))
    ws.freeze_panes = "A2"
    for r_idx, row in enumerate(rows, start=2):
        for c_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=value)
            cell.alignment = CENTER if c_idx in center_cols else WRAP
            cell.border = BORDER
            cell.font = Font(size=9)


def main() -> None:
    parser = argparse.ArgumentParser(description="导出评测结果为 Excel（含完整回答）")
    parser.add_argument("--report", default=str(REPORT), help="评测结果 JSON")
    parser.add_argument("--testset", default=str(TESTSET), help="用例集 JSON")
    parser.add_argument("--out", default=str(OUT), help="输出 xlsx")
    args = parser.parse_args()
    data = json.loads(Path(args.report).read_text(encoding="utf-8"))
    results = data["results"]
    cases = {c["id"]: c for c in json.loads(Path(args.testset).read_text(encoding="utf-8"))}
    summary = data["summary"]
    wb = Workbook()

    # ---------- 汇总 ----------
    ws = wb.active
    ws.title = "汇总"
    ws.column_dimensions["A"].width = 30
    for col in "BCDEF":
        ws.column_dimensions[col].width = 15
    total_n = summary["total"]
    ws["A1"] = f"内部客服副驾 · {total_n} 条评测结果（含完整回答）"
    ws["A1"].font = Font(bold=True, size=15, color="1F3864")
    ws.merge_cells("A1:E1")
    ws["A2"] = f"v3.8 · 2026-10-30 · {total_n} 条 × 1 次 · Dify workflow"
    ws["A2"].font = Font(size=9, color="666666")
    metrics = [
        ("任务解决率 pass@1", f"{summary['pass1'] * 100:.1f}%"),
        ("通过/总数", f"{summary['passed']}/{summary['total']}"),
        ("P50", f"{summary['p50']:.2f}s"),
        ("P95", f"{summary['p95']:.2f}s"),
    ]
    for i, (name, value) in enumerate(metrics):
        ws.cell(row=4 + i, column=1, value=name)
        cell = ws.cell(row=4 + i, column=2, value=value)
        cell.font = Font(bold=True, size=11)
        cell.alignment = Alignment(horizontal="center")

    scene_counts = {}
    for r in results:
        item = scene_counts.setdefault(r["scene"], [0, 0])
        item[0] += 1
        item[1] += 1 if r["passed"] else 0
    row = 10
    ws.cell(row=row, column=1, value="分场景").font = Font(bold=True, size=12, color="1F3864")
    for i, h in enumerate(["场景", "条数", "通过", "通过率"], start=1):
        ws.cell(row=row + 1, column=i, value=h)
    header(ws, row + 1, 4)
    for scene, (total, passed) in sorted(scene_counts.items(), key=lambda kv: -kv[1][1] / kv[1][0]):
        row += 1
        ws.cell(row=row, column=1, value=SCENE_CN.get(scene, scene))
        ws.cell(row=row, column=2, value=total).alignment = Alignment(horizontal="center")
        ws.cell(row=row, column=3, value=passed).alignment = Alignment(horizontal="center")
        cell = ws.cell(row=row, column=4, value=f"{passed / total * 100:.1f}%")
        cell.alignment = Alignment(horizontal="center")
        cell.fill = PASS_FILL if passed / total >= 0.6 else FAIL_FILL
        for col in range(1, 5):
            ws.cell(row=row, column=col).border = BORDER

    # ---------- 明细 ----------
    detail_headers = [
        "编号", "场景", "员工", "买家原话", "期望动作", "实际动作", "期望升级", "实际升级",
        "结论", "失败原因", "客服回复全文", "依据", "新人解释", "耗时(s)",
    ]
    detail_widths = [6, 7, 6, 36, 13, 11, 8, 8, 7, 34, 80, 44, 28, 8]
    rows = []
    all_rows = []
    for r in results:
        case = cases.get(r["id"], {})
        obj = clean_answer(r["answer"])
        evidence = obj.get("evidence") if isinstance(obj.get("evidence"), list) else []
        expect_action = case.get("expect_action_any") or [case.get("expect_action")]
        expected_esc = case.get("expect_escalate")
        base = [
            r["id"], SCENE_CN.get(r["scene"], r["scene"]), LEVEL_CN.get(r["agent_level"], r["agent_level"]),
            case.get("buyer_message") or "", "/".join(expect_action), obj.get("next_action") or "",
            "不判" if expected_esc is None else ("是" if expected_esc else "否"),
            "是" if obj.get("escalate") else "否",
            "通过" if r["passed"] else "不通过",
            "；".join(r.get("fails") or []),
            obj.get("reply") or "",
            "\n".join(f"{i + 1}. {e}" for i, e in enumerate(evidence)) if evidence else "（无）",
            obj.get("explanation") or "（空）",
            round(r.get("seconds") or 0, 1),
        ]
        all_rows.append(base)
        if not r["passed"]:
            rows.append(base)

    ws2 = wb.create_sheet("用例明细")
    write_table(ws2, detail_headers, detail_widths, all_rows, {1, 2, 3, 5, 6, 7, 8, 9, 14})
    for idx in range(2, 2 + len(all_rows)):
        cell = ws2.cell(row=idx, column=9)
        passed = cell.value == "通过"
        cell.fill = PASS_FILL if passed else FAIL_FILL
        cell.font = Font(size=9, bold=True, color="375623" if passed else "9C0006")

    ws3 = wb.create_sheet("失败用例")
    write_table(ws3, detail_headers, detail_widths, rows, {1, 2, 3, 5, 6, 7, 8, 9, 14})
    for idx in range(2, 2 + len(rows)):
        ws3.cell(row=idx, column=9).fill = FAIL_FILL
        ws3.cell(row=idx, column=9).font = Font(size=9, bold=True, color="9C0006")

    # ---------- 原始输出 ----------
    ws4 = wb.create_sheet("原始输出")
    ws4.column_dimensions["A"].width = 6
    ws4.column_dimensions["B"].width = 140
    ws4.cell(row=1, column=1, value="编号")
    ws4.cell(row=1, column=2, value="Dify 原始 answer（含 <think> 推理文本）")
    header(ws4, 1, 2)
    ws4.freeze_panes = "A2"
    for idx, r in enumerate(results, start=2):
        ws4.cell(row=idx, column=1, value=r["id"]).alignment = CENTER
        cell = ws4.cell(row=idx, column=2, value=r["answer"] or "")
        cell.alignment = WRAP
        cell.font = Font(size=8)
        ws4.row_dimensions[idx].height = min(409, max(30, len(r["answer"] or "") * 0.5))

    # ---------- 说明 ----------
    ws5 = wb.create_sheet("说明")
    ws5.column_dimensions["A"].width = 110
    notes = [
        "口径与说明",
        "",
        "1. 通过判定：JSON 合法 + 五字段齐全 + reply 无内部词 + 依据满足每题要求 + explanation 符合新/老员工规则 + 动作与升级符合预期 + 禁词未触发。",
        "2. 期望动作有多个可选值时命中任一即通过；期望升级标注“不判”的题不校验 escalate。",
        "3. 客服回复全文来自模型输出的 reply 字段；依据为 evidence 数组原文；“原始输出”页保留 <think> 推理，便于判断模型思路。",
        "4. 本轮跑前统一修正了 18 条用例的断言错误（禁词过宽、动作写死、升级期望与项目规则冲突），否则分数会被断言本身压低。",
        "5. 已知问题：模型输出携带 <think> 推理文本，员工端可见；知识库未补政策/话术 4 个文件，政策/促销/技术类证据为空。",
        "6. 用例 51 因“拆开”禁词误判记失败，该禁词已修正，但 v1 技术提示词仍强制追问型号，故仍不通过。",
        "7. 数据源：evaluation/reports/copilot_eval/latest.json。",
    ]
    for i, text in enumerate(notes, start=1):
        cell = ws5.cell(row=i, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.font = Font(size=10, bold=(i == 1))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print("written", out_path, "rows", len(all_rows))


if __name__ == "__main__":
    main()
