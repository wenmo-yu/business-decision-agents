"""命令行轨迹评测入口：python -m app.evals.runner --trace output/.../trace.jsonl --cases tests/fixtures/eval_cases.jsonl"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evals.trajectory import evaluate_trajectory, load_trace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", default="artifacts/eval-result.json")
    args = parser.parse_args()
    trace = load_trace(args.trace)
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines() if line.strip()]
    results = [{"id": case["id"], **evaluate_trajectory(trace, case["expectation"])} for case in cases]
    payload = {"passed": all(item["passed"] for item in results), "results": results}
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
