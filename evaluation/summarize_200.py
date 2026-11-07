"""200 条正式报告的统计层：pass@1 + Wilson 95% 区间，按场景/员工拆分。"""
import argparse
import json
import math
from pathlib import Path
from collections import Counter

Z = 1.96


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n * 100:.1f}% [{lo * 100:.1f}%, {hi * 100:.1f}%]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    args = ap.parse_args()
    d = json.loads(Path(args.report).read_text(encoding="utf-8"))
    results = d["results"]
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"总体 pass@1: {pct(passed, total)}")
    for key, label in (("scene", "场景"), ("agent_level", "员工")):
        groups = {}
        for r in results:
            groups.setdefault(r[key], []).append(r["passed"])
        print(f"\n按{label}:")
        for name, flags in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            print(f"  {name}: {pct(sum(flags), len(flags))}")

    reasons = Counter()
    for r in results:
        if not r["passed"]:
            for f in r["fails"]:
                reasons[f.split(":")[0][:24]] += 1
    print("\n失败原因 Top:")
    for reason, n in reasons.most_common(10):
        print(f"  {n:>3}  {reason}")

    import statistics
    secs = [r["seconds"] for r in results if r.get("seconds")]
    if secs:
        secs.sort()
        print(f"\nP50 {statistics.median(secs):.2f}s / P95 {secs[int(len(secs) * 0.95)]:.2f}s")


if __name__ == "__main__":
    main()
