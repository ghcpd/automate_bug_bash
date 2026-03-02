"""S8 · Oracle Sweep & Acceptance → data/accepted_tasks.json

Runs `harbor run -p <task_dir> -a oracle` for each task N times and
accepts tasks that achieve mean score >= threshold with low variance.

Usage:
    python -m pipeline.steps.s8_oracle_sweep
    python -m pipeline.steps.s8_oracle_sweep --runs 1  # quick test
    python -m pipeline.steps.s8_oracle_sweep --tasks 5 --runs 1  # test on 5 tasks
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
from pathlib import Path

import yaml

from ..models import AcceptedTask, ScoredRepo

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
INPUT_FILE = DATA_DIR / "scored_repos.json"
TASKS_DIR = Path(__file__).parent.parent.parent / "tasks"
OUTPUT_FILE = DATA_DIR / "accepted_tasks.json"


def _run_oracle(task_dir: Path, jobs_dir: Path, timeout: int = 600) -> float:
    """Run `harbor run -p <task_dir> -a oracle` and return the reward score."""
    cmd = [
        "harbor", "run",
        "-p", str(task_dir),
        "-a", "oracle",
        "--jobs-dir", str(jobs_dir),
        "--quiet",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=task_dir.parent.parent,  # repo root
        )
        # Harbor writes result.json to jobs_dir/<timestamp>/result.json
        # Find the most recent result.json
        result_files = sorted(
            jobs_dir.glob("*/*/result.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if result_files:
            try:
                data = json.loads(result_files[0].read_text())
                # Harbor writes score at verifier_result.rewards.score (multi-key)
                # or verifier_result.rewards.reward (plain scalar reward.txt)
                rewards = data.get("verifier_result", {}).get("rewards", {})
                score_val = rewards.get("score") if rewards.get("score") is not None \
                    else rewards.get("reward")
                if score_val is not None:
                    return float(score_val)
            except Exception:
                pass
        # If harbor returned non-zero, treat as failure
        return 0.0 if result.returncode != 0 else 0.0
    except subprocess.TimeoutExpired:
        return 0.0
    except FileNotFoundError:
        raise RuntimeError(
            "harbor command not found. Is Harbor installed and on PATH?"
        )


def run(n_runs: int | None = None, max_tasks: int | None = None) -> list[AcceptedTask]:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    oracle_cfg = config["oracle"]
    n_runs = n_runs or oracle_cfg["runs"]
    accept_score = oracle_cfg["acceptance_score"]
    accept_stdev = oracle_cfg["acceptance_stdev"]

    if not INPUT_FILE.exists():
        print(f"[S8] ERROR: {INPUT_FILE} not found — run S6 first")
        return []

    scored = {r["repo"]: r for r in json.loads(INPUT_FILE.read_text())}

    task_dirs = sorted(d for d in TASKS_DIR.iterdir() if d.is_dir()) if TASKS_DIR.exists() else []
    if max_tasks is not None:
        task_dirs = task_dirs[:max_tasks]
    print(f"[S8] Running oracle sweep: {len(task_dirs)} tasks × {n_runs} runs")

    # Use a temp jobs dir per run to avoid cross-contamination
    jobs_dir = DATA_DIR / "oracle_jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    # Load existing (idempotent) — key by task dir NAME (not full path) for portability
    existing: dict[str, AcceptedTask] = {}
    if OUTPUT_FILE.exists():
        for raw in json.loads(OUTPUT_FILE.read_text()):
            a = AcceptedTask(**raw)
            # Support both old (full path) and new (name-only) keys
            existing[Path(a.task_dir).name] = a
        print(f"[S8] Resuming — {len(existing)} tasks already swept")

    results: dict[str, AcceptedTask] = dict(existing)

    for task_dir in task_dirs:
        task_key = task_dir.name  # name-only key for cross-machine portability
        if task_key in results:
            continue

        # Derive repo from task_dir name: owner__repo__sha (all lowercase)
        parts = task_dir.name.split("__")
        # scored keys are original-case repo names; search case-insensitively
        repo_key_lower = f"{parts[0]}/{parts[1]}" if len(parts) >= 3 else task_dir.name
        scored_entry = next(
            (v for k, v in scored.items() if k.lower().replace("/", "/") == repo_key_lower),
            {}
        )
        sha = scored_entry.get("sha", parts[2] if len(parts) >= 3 else "")
        difficulty = scored_entry.get("difficulty", "medium")

        scores: list[float] = []
        print(f"  {task_dir.name} ", end="", flush=True)
        for i in range(n_runs):
            run_jobs_dir = jobs_dir / task_dir.name / str(i)
            run_jobs_dir.mkdir(parents=True, exist_ok=True)
            score = _run_oracle(task_dir, run_jobs_dir)
            scores.append(score)
            print(f"{score:.2f} ", end="", flush=True)
        print()

        mean = sum(scores) / len(scores)
        stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0
        accepted = mean >= accept_score and stdev < accept_stdev
        reason = None
        if not accepted:
            if mean < accept_score:
                reason = f"oracle_below_threshold: mean={mean:.3f}"
            else:
                reason = f"flaky_tests: stdev={stdev:.3f}"

        result = AcceptedTask(
            task_dir=task_key,
            repo=scored_entry.get("repo", repo_key_lower),
            sha=sha,
            difficulty=difficulty,
            oracle_scores=scores,
            mean_score=round(mean, 4),
            accepted=accepted,
            rejection_reason=reason,
        )
        results[task_key] = result

        # Incremental save
        OUTPUT_FILE.write_text(
            json.dumps([r.model_dump() for r in results.values()],
                       indent=2, default=str)
        )

    accepted_list = [r for r in results.values() if r.accepted]
    print(f"\n[S8] Done. {len(accepted_list)}/{len(results)} tasks accepted "
          f"→ {OUTPUT_FILE}")
    return list(results.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="S8: Oracle sweep & acceptance")
    parser.add_argument("--runs", type=int, default=None,
                        help="Override number of oracle runs per task")
    parser.add_argument("--tasks", type=int, default=None,
                        help="Max number of tasks to sweep (for testing)")
    args = parser.parse_args()
    run(n_runs=args.runs, max_tasks=args.tasks)


if __name__ == "__main__":
    main()
