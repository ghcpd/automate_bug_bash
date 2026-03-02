"""S7 · Harbor Task Generation → tasks/

Usage:
    python -m pipeline.steps.s7_task_gen
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from ..models import CIBaseline, ScoredRepo
from ..strategies import get_strategy
from ..task_writer import TaskWriter

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
INPUT_FILE = DATA_DIR / "scored_repos.json"
BASELINE_FILE = DATA_DIR / "ci_baselines.json"
TASKS_DIR = Path(__file__).parent.parent.parent / "tasks"


def run() -> list[Path]:
    if not INPUT_FILE.exists():
        print(f"[S7] ERROR: {INPUT_FILE} not found — run S4 first")
        return []

    scored = [ScoredRepo(**r) for r in json.loads(INPUT_FILE.read_text())]
    print(f"[S7] Generating Harbor tasks for {len(scored)} repos")

    # Baseline lookup for expected_pass
    baselines: dict[str, CIBaseline] = {}
    if BASELINE_FILE.exists():
        for raw in json.loads(BASELINE_FILE.read_text()):
            b = CIBaseline(**raw)
            baselines[b.repo] = b

    strategy = get_strategy("python")
    writer = TaskWriter(TASKS_DIR, strategy)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    skipped = 0
    errors = 0

    for repo in scored:
        baseline = baselines.get(repo.repo)
        if baseline is None:
            print(f"  WARN: no baseline for {repo.repo} — skipping")
            skipped += 1
            continue

        owner, name = repo.repo.split("/", 1)
        short_sha = repo.sha[:7]
        task_name = strategy.task_name(owner, name, short_sha)
        task_dir = TASKS_DIR / task_name

        if task_dir.exists():
            print(f"  SKIP {task_name} (already exists)")
            generated.append(task_dir)
            continue

        try:
            task_dir = writer.write(repo, expected_pass=baseline.expected_pass)
            generated.append(task_dir)
            print(f"  OK   {task_name} [{repo.difficulty}]")
        except Exception as exc:
            print(f"  ERR  {repo.repo}: {exc}")
            errors += 1

    print(f"\n[S7] Done. {len(generated)} tasks written, "
          f"{skipped} skipped, {errors} errors → {TASKS_DIR}")
    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description="S5: Harbor task generation")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
