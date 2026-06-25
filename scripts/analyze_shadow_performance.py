#!/usr/bin/env python
"""Analyze shadow trading decision logs or shadow_decisions JSONL exports."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.shadow.performance_analysis import (
    analyze_log_file,
    format_human_summary,
    save_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze shadow decision logs")
    parser.add_argument(
        "input",
        help="decision_log JSONL/app log or shadow_decisions DB export JSONL",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="shadow_performance_summary.json",
        help="Path for machine-readable JSON summary",
    )
    args = parser.parse_args()

    summary = analyze_log_file(args.input)
    save_summary(summary, Path(args.output))
    print(format_human_summary(summary))
    print(f"\nWrote machine-readable summary: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
