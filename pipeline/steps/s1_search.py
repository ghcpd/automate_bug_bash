"""S1 · Repo Pre-filter from local repo list → data/candidates.json

Reads pipeline/data/repo_lists/repo_list_python.jsonl (pre-built list with
static analysis results) and filters to repos that have a detectable pytest
setup. No GitHub API calls are made in this step.

Usage:
    python -m pipeline.steps.s1_search
    python -m pipeline.steps.s1_search --max 500  # cap output size
    python -m pipeline.steps.s1_search --min-tests 10  # require ≥N estimated tests
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..models import Candidate

DATA_DIR = Path(__file__).parent.parent.parent / "data"
REPO_LIST = DATA_DIR / "repo_lists" / "repo_list_python.jsonl"
OUTPUT_FILE = DATA_DIR / "candidates.json"


def _dep_file(ctx: dict) -> str | None:
    """Return the first detected dependency file, or None."""
    if ctx.get("has_pyproject_toml"):
        return "pyproject.toml"
    if ctx.get("has_setup_py"):
        return "setup.py"
    if ctx.get("has_requirements_txt"):
        return "requirements.txt"
    if ctx.get("has_setup_cfg"):
        return "setup.cfg"
    return None


def run(max_candidates: int | None = None, min_tests: int = 1) -> list[Candidate]:
    if not REPO_LIST.exists():
        raise FileNotFoundError(f"Repo list not found: {REPO_LIST}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    candidates: list[Candidate] = []
    total = skipped_no_tests = skipped_no_dep = 0

    with REPO_LIST.open() as f:
        for line in f:
            if max_candidates and len(candidates) >= max_candidates:
                break
            total += 1
            record = json.loads(line)

            # Skip repos without prescan data or below test threshold
            prescan = record.get("prescan") or {}
            py = prescan.get("python")
            if not py or py.get("total_estimated", 0) < min_tests:
                skipped_no_tests += 1
                continue

            ctx = py.get("repo_context", {})
            dep = _dep_file(ctx)
            if dep is None:
                skipped_no_dep += 1
                continue

            candidates.append(Candidate(
                repo=record["repo"],
                sha=record["commit"],
                size_kb=record.get("size_kb", 0),
                dep_file=dep,
                has_tests=bool(py.get("test_files")),
                prescan_count=py.get("total_estimated", 0),
            ))

    OUTPUT_FILE.write_text(
        json.dumps([c.model_dump() for c in candidates], indent=2, default=str)
    )
    print(f"[S1] Processed {total} repos from list")
    print(f"     Skipped {skipped_no_tests} (no/insufficient tests), "
          f"{skipped_no_dep} (no dep file)")
    print(f"     {len(candidates)} candidates saved → {OUTPUT_FILE}")
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="S1: Load and pre-filter repo list")
    parser.add_argument("--max", type=int, default=None,
                        help="Maximum candidates to output")
    parser.add_argument("--min-tests", type=int, default=1,
                        help="Minimum estimated test count (default: 1)")
    args = parser.parse_args()
    run(max_candidates=args.max, min_tests=args.min_tests)


if __name__ == "__main__":
    main()
