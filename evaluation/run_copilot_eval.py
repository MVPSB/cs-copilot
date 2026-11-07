#!/usr/bin/env python3
"""内部客服副驾评测：跑改版后的 Dify Chatflow，校验结构化 JSON 输出。

与 run_eval.py（对外客服版）并列，互不影响。

用法:
    python evaluation/run_copilot_eval.py --check-inputs      # 确认 3 个输入变量已生效
    python evaluation/run_copilot_eval.py --runs 1 --limit 5 # 冒烟
    python evaluation/run_copilot_eval.py --runs 1           # 全量 30 条
    python evaluation/run_copilot_eval.py --only 17,23,24    # 只跑指定用例

配置读项目根目录 .env（DIFY_BASE_URL / DIFY_APP_API_KEY），环境变量优先。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEST = ROOT / "evaluation" / "testset_copilot.json"
DEFAULT_OUT = ROOT / "evaluation" / "reports" / "copilot_eval"
REQUIRED_INPUTS = ["order_no", "agent_level", "scene_hint"]
ALLOWED_ACTIONS = {"直接回复", "追问订单号", "追问产品", "查库存", "查物流", "转主管"}
REQUIRED_KEYS = ["reply", "evidence", "explanation", "next_action", "escalate"]


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def http_json(method: str, url: str, key: str, payload: dict | None = None, timeout: int = 180):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body), time.perf_counter() - started, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed, time.perf_counter() - started, body
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}, time.perf_counter() - started, str(exc)


def strip_reasoning(answer: str) -> str:
    """去掉 DeepSeek 的 <think> 推理文本（含未闭合的情况）。"""
    text = (answer or "").strip()
    text = re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.S)
    return text.strip()


def parse_model_json(answer: str):
    """从模型回答里抠出 JSON；容忍 ```json 代码块、前面带推理文本或废话。"""
    text = strip_reasoning(answer)
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text, *re.findall(r"\{.*\}", text, re.S)]
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    # 从第一个 { 开始逐字符尝试，容忍 JSON 前后的废话
    start = text.find("{")
    if start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


NEGATION_RE = re.compile(r"(不要|别|不能|不得|切勿|请勿|不建议|无需|不用|避免|禁止|没有|并非|不是)[^。！？\n]{0,10}$")


def contains_violation(reply: str, needle: str) -> bool:
    """禁词出现在“否定句”里不算违规，例如“不要自己拆机”“并没有 5000 元”。"""
    for match in re.finditer(re.escape(needle), reply):
        prefix = reply[max(0, match.start() - 12):match.start()]
        if not NEGATION_RE.search(prefix):
            return True
    return False


def check_case(case: dict, obj: dict | None) -> list[str]:
    fails: list[str] = []
    if obj is None:
        return ["回答不是合法 JSON"]

    missing = [key for key in REQUIRED_KEYS if key not in obj]
    if missing:
        return [f"缺字段: {', '.join(missing)}"]

    reply = str(obj.get("reply") or "").strip()
    if len(reply) < 8:
        fails.append("reply 过短或为空")
    if "知识库" in reply or "检索到" in reply or "根据文档" in reply:
        fails.append("reply 出现内部词（知识库/检索）")

    evidence = obj.get("evidence")
    if not isinstance(evidence, list):
        fails.append("evidence 不是数组")
    elif case.get("expect_evidence"):
        real = [str(item).strip() for item in evidence if str(item).strip()]
        if not real:
            fails.append("evidence 为空（本题要求有依据）")
        elif all(item == "知识库未覆盖" for item in real):
            fails.append("evidence 只有“知识库未覆盖”")

    explanation = str(obj.get("explanation") or "").strip()
    if case.get("agent_level") == "new":
        if not explanation:
            fails.append("新人员工缺 explanation")
    else:
        if explanation:
            fails.append("老员工不应填 explanation")

    action = str(obj.get("next_action") or "").strip()
    if action not in ALLOWED_ACTIONS:
        fails.append(f"next_action 非法: {action}")
    allowed_actions = case.get("expect_action_any")
    if allowed_actions:
        if action not in allowed_actions:
            fails.append(f"next_action={action}，期望 {'/'.join(allowed_actions)}")
    else:
        expected_action = case.get("expect_action")
        if expected_action and action != expected_action:
            fails.append(f"next_action={action}，期望 {expected_action}")

    escalate = obj.get("escalate")
    if "expect_escalate" in case and case["expect_escalate"] is not None:
        if not isinstance(escalate, bool):
            fails.append("escalate 不是 bool")
        elif escalate != case["expect_escalate"]:
            fails.append(f"escalate={escalate}，期望 {case['expect_escalate']}")

    for needle in case.get("must_contain") or []:
        if needle not in reply:
            fails.append(f"reply 缺少必含: {needle}")
    for needle in case.get("must_not_contain") or []:
        if contains_violation(reply, needle):
            fails.append(f"reply 出现禁词: {needle}")

    return fails


def run_case(case: dict, cfg: dict) -> dict:
    payload = {
        "inputs": {
            "order_no": case.get("order_no") or "",
            "agent_level": case.get("agent_level") or "veteran",
            "scene_hint": case.get("scene_hint") or "auto",
        },
        "query": case["buyer_message"],
        "response_mode": "blocking",
        "user": "copilot-eval",
    }
    status, data, seconds, raw = http_json(
        "POST", f"{cfg['base_url']}/chat-messages", cfg["key"], payload, cfg["timeout"]
    )
    answer = str(data.get("answer") or "") if isinstance(data, dict) else ""
    obj = parse_model_json(answer)
    fails = check_case(case, obj) if status == 200 else [f"HTTP {status}: {str(data)[:180]}"]
    return {
        "id": case["id"],
        "scene": case.get("scene"),
        "agent_level": case.get("agent_level"),
        "scene_hint": case.get("scene_hint"),
        "status": status,
        "seconds": round(seconds, 2),
        "passed": not fails,
        "fails": fails,
        "answer": answer[:8000],
        "raw": raw[:600] if status != 200 else "",
    }


def check_inputs(cfg: dict) -> int:
    status, data, _, raw = http_json("GET", f"{cfg['base_url']}/parameters", cfg["key"], None, 30)
    if status != 200:
        print(f"[FAIL] GET /parameters -> HTTP {status}: {raw[:200]}")
        return 1
    names = set()
    for item in (data or {}).get("user_input_form", []):
        for field in item.values():
            if isinstance(field, dict) and field.get("variable"):
                names.add(field["variable"])
    print(f"接口可见输入变量: {sorted(names) or '无'}")
    missing = [name for name in REQUIRED_INPUTS if name not in names]
    if missing:
        print(f"[FAIL] 缺少变量: {missing}（先按 docs/copilot-migration.md 步骤 1 添加）")
        return 1
    print("[OK] 3 个输入变量均已生效")
    return 0


def summarize(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    latencies = sorted(item["seconds"] for item in results if item["status"] == 200)
    p95 = latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))] if latencies else 0
    groups: dict[str, list[bool]] = {}
    by_level: dict[str, list[bool]] = {}
    for item in results:
        groups.setdefault(item["scene"], []).append(item["passed"])
        by_level.setdefault(item["agent_level"], []).append(item["passed"])
    return {
        "total": total,
        "passed": passed,
        "pass1": round(passed / total, 3) if total else 0,
        "p50": round(latencies[len(latencies) // 2], 2) if latencies else 0,
        "p95": round(p95, 2),
        "by_scene": {key: round(sum(vals) / len(vals), 3) for key, vals in sorted(groups.items())},
        "by_level": {key: round(sum(vals) / len(vals), 3) for key, vals in sorted(by_level.items())},
    }


def write_report(results: list[dict], summary: dict, out_dir: Path, meta: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "latest.json"
    json_path.write_text(
        json.dumps({"meta": meta, "summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# 内部客服副驾评测报告",
        "",
        f"- 时间：{meta['time']}",
        f"- 用例：{summary['total']} 条，通过 {summary['passed']} 条",
        f"- 通过率 pass@1：**{summary['pass1']:.1%}**",
        f"- P50 {summary['p50']}s / P95 {summary['p95']}s",
        "",
        "## 分组通过率",
        "",
        "| 场景 | 通过率 |",
        "|---|---|",
    ]
    for key, value in summary["by_scene"].items():
        lines.append(f"| {key} | {value:.1%} |")
    lines += ["", "| 员工经验 | 通过率 |", "|---|---|"]
    for key, value in summary["by_level"].items():
        lines.append(f"| {key} | {value:.1%} |")

    failed = [item for item in results if not item["passed"]]
    lines += ["", f"## 失败用例（{len(failed)} 条）", ""]
    if not failed:
        lines.append("无。")
    for item in failed:
        lines.append(f"### 用例 {item['id']}（{item['scene']} / {item['agent_level']}）")
        lines.append("")
        lines.append(f"- 失败原因：{'；'.join(item['fails'])}")
        lines.append(f"- 原始回答：`{item['answer'][:300]}`")
        lines.append("")

    md_path = out_dir / "latest.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="内部客服副驾评测")
    parser.add_argument("--testset", default=str(DEFAULT_TEST))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--runs", type=int, default=1, help="同一集合重复次数（默认 1）")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", default="", help="只跑指定 id，逗号分隔")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--check-inputs", action="store_true", help="仅检查输入变量是否已生效")
    args = parser.parse_args(argv)

    env = load_env(ROOT / ".env")
    cfg = {
        "base_url": (args.base_url or os.environ.get("DIFY_BASE_URL") or env.get("DIFY_BASE_URL") or "http://localhost/v1").rstrip("/"),
        "key": os.environ.get("DIFY_APP_API_KEY") or env.get("DIFY_APP_API_KEY") or "",
        "timeout": args.timeout,
    }
    if not cfg["key"]:
        print("[FAIL] 缺少 DIFY_APP_API_KEY（写进 .env 或设环境变量）")
        return 2
    print(f"Dify: {cfg['base_url']}")

    if args.check_inputs:
        return check_inputs(cfg)

    cases = json.loads(Path(args.testset).read_text(encoding="utf-8"))
    if args.only:
        wanted = {int(part) for part in args.only.split(",") if part.strip()}
        cases = [case for case in cases if case["id"] in wanted]
    if args.limit:
        cases = cases[: args.limit]

    results: list[dict] = []
    for run_idx in range(args.runs):
        if args.runs > 1:
            print(f"\n=== 第 {run_idx + 1}/{args.runs} 遍 ===")
        for index, case in enumerate(cases, 1):
            result = run_case(case, cfg)
            result["run"] = run_idx
            results.append(result)
            flag = "PASS" if result["passed"] else "FAIL"
            detail = "" if result["passed"] else " | " + "；".join(result["fails"])
            print(f"[{index:02d}/{len(cases)}] #{case['id']:<2} {case['scene']:<10} {flag} {result['seconds']:.1f}s{detail}")
            if result["status"] == 401:
                print("[提示] 401：Key 不对或应用已删。检查 .env 里的 DIFY_APP_API_KEY。")
                return 3

    summary = summarize(results)
    md_path = write_report(
        results,
        summary,
        Path(args.out),
        {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "base_url": cfg["base_url"], "runs": args.runs},
    )
    print("\n=== 汇总 ===")
    print(f"通过率 pass@1: {summary['pass1']:.1%} ({summary['passed']}/{summary['total']})")
    print(f"P50 {summary['p50']}s / P95 {summary['p95']}s")
    print("场景: " + ", ".join(f"{key} {value:.0%}" for key, value in summary["by_scene"].items()))
    print("员工: " + ", ".join(f"{key} {value:.0%}" for key, value in summary["by_level"].items()))
    print(f"报告: {md_path}")
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
