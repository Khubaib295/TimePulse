"""Repeatable Windows startup profiler for TimePulse.

Examples:
    python benchmark_startup.py --source --runs 5
    python benchmark_startup.py --exe dist\\TimePulse\\TimePulse.exe --runs 5

The target is stopped after it writes its opt-in startup profile. This measures
startup only; it does not exercise an alarm or leave a TimePulse instance open.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


MILESTONE_PATTERN = re.compile(r"^\s+(\w+)\s+:\s+([0-9.]+) ms", re.MULTILINE)


def parse_profile(path: Path) -> dict[str, float]:
    return {name: float(milliseconds) for name, milliseconds in MILESTONE_PATTERN.findall(
        path.read_text(encoding="utf-8")
    )}


def run_once(command: list[str], report_path: Path, timeout: float) -> dict[str, float]:
    environment = os.environ.copy()
    environment["TIMEPULSE_PROFILE_STARTUP"] = "1"
    environment["TIMEPULSE_PROFILE_STARTUP_FILE"] = str(report_path)
    started = time.perf_counter()
    log_path = report_path.with_suffix(".log")
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        process = subprocess.Popen(
            command, env=environment, stdout=log_file, stderr=subprocess.STDOUT
        )
    try:
        deadline = started + timeout
        while time.perf_counter() < deadline:
            if report_path.exists():
                result = parse_profile(report_path)
                result["benchmark_wall_clock"] = (time.perf_counter() - started) * 1000
                return result
            if process.poll() is not None:
                output = log_path.read_text(encoding="utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"Target exited before profiling (exit code {process.returncode}): {output}"
                )
            time.sleep(0.025)
        output = log_path.read_text(encoding="utf-8", errors="replace").strip()
        raise TimeoutError(
            f"No startup profile was written within {timeout:.1f} seconds. Output: {output}"
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def summarize(samples: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    keys = sorted({key for sample in samples for key in sample})
    return {
        key: {
            "min_ms": round(min(sample[key] for sample in samples if key in sample), 2),
            "mean_ms": round(sum(sample[key] for sample in samples if key in sample) /
                             sum(key in sample for sample in samples), 2),
            "max_ms": round(max(sample[key] for sample in samples if key in sample), 2),
        }
        for key in keys
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure TimePulse startup milestones.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--source", action="store_true", help="Run TimePulse.py with this Python.")
    target.add_argument("--exe", type=Path, help="Run a packaged TimePulse.exe.")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=Path("startup-benchmark.json"))
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    root = Path(__file__).resolve().parent
    command = [sys.executable, str(root / "TimePulse.py")] if args.source else [str(args.exe.resolve())]
    report_dir = root / ".startup-benchmark"
    report_dir.mkdir(exist_ok=True)
    samples = []
    for run_number in range(1, args.runs + 1):
        report_path = report_dir / f"run-{run_number}.txt"
        report_path.unlink(missing_ok=True)
        sample = run_once(command, report_path, args.timeout)
        samples.append(sample)
        print(f"Run {run_number}/{args.runs}: first idle {sample.get('first_idle_callback', 0):.2f} ms")

    results = {"command": command, "runs": samples, "summary": summarize(samples)}
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
