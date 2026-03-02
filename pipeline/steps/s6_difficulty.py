"""S6 · Difficulty Scoring → data/scored_repos.json

Merges two sources:
  - trivial_success repos from triage.json  → difficulty from setup complexity
  - needs_agent repos from agent_results.json → difficulty from S5 pass_rate

Usage:
    python -m pipeline.steps.s6_difficulty
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import yaml

from ..models import AgentResult, CIBaseline, DifficultyBreakdown, ScoredRepo, VerifiedRepo

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
TRIAGE_FILE = DATA_DIR / "triage.json"
AGENT_FILE = DATA_DIR / "agent_results.json"
BASELINE_FILE = DATA_DIR / "ci_baselines.json"
OUTPUT_FILE = DATA_DIR / "scored_repos.json"

# Difficulty dimension weights for trivial_success repos (must sum to 1.0)
_WEIGHTS = {
    "setup_steps": 0.20,
    "build_required": 0.20,
    "setup_time": 0.20,
    "error_diversity": 0.15,
    "test_count": 0.25,
}


def _score_dimension(value: float | int | bool, thresholds: tuple) -> float:
    """Map a raw value to [0, 1] using easy/hard thresholds."""
    easy_max, hard_min = thresholds
    if value <= easy_max:
        return 0.0
    if value >= hard_min:
        return 1.0
    return (value - easy_max) / (hard_min - easy_max)


def _compute_breakdown(verified: VerifiedRepo, baseline: CIBaseline) -> DifficultyBreakdown:
    cmd = verified.setup_strategy or ""
    setup_steps = max(1, cmd.count("&&") + 1)
    build_required = any(kw in cmd.lower() for kw in ("make", "cmake", "compile", "build"))
    error_diversity = max(0, setup_steps - 1)

    s_steps = _score_dimension(setup_steps, (1, 3))
    s_build = 1.0 if build_required else 0.0
    s_time = _score_dimension(verified.setup_time_sec, (30, 120))
    s_errors = _score_dimension(error_diversity, (1, 4))
    s_tests = _score_dimension(baseline.expected_pass, (50, 500))

    composite = (
        s_steps * _WEIGHTS["setup_steps"]
        + s_build * _WEIGHTS["build_required"]
        + s_time * _WEIGHTS["setup_time"]
        + s_errors * _WEIGHTS["error_diversity"]
        + s_tests * _WEIGHTS["test_count"]
    )
    return DifficultyBreakdown(
        setup_steps=setup_steps,
        build_required=build_required,
        setup_time_sec=verified.setup_time_sec,
        error_diversity=error_diversity,
        test_count=baseline.expected_pass,
        composite_score=round(composite, 4),
    )


def _trivial_label(composite: float) -> str:
    if composite < 0.35:
        return "easy"
    if composite < 0.65:
        return "medium"
    return "hard"


def _stratified_sample(scored: list[ScoredRepo], target: int,
                       targets: dict[str, float]) -> list[ScoredRepo]:
    """Return a stratified sample of `target` repos matching difficulty distribution."""
    buckets: dict[str, list[ScoredRepo]] = {k: [] for k in ("easy", "medium", "hard", "very_hard")}
    for r in scored:
        buckets.setdefault(r.difficulty, []).append(r)

    result: list[ScoredRepo] = []
    for label, fraction in targets.items():
        n = int(target * fraction)
        pool = buckets.get(label, [])
        random.shuffle(pool)
        result.extend(pool[:n])

    remaining = target - len(result)
    all_remaining = [r for r in scored if r not in result]
    random.shuffle(all_remaining)
    result.extend(all_remaining[:remaining])
    return result[:target]


def run() -> list[ScoredRepo]:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    diff_cfg = config["difficulty"]
    target_size = config["corpus"]["target_size"]

    if not TRIAGE_FILE.exists():
        print(f"[S6] ERROR: {TRIAGE_FILE} not found — run S3 first")
        return []

    # Build baseline lookup
    baselines: dict[str, CIBaseline] = {}
    if BASELINE_FILE.exists():
        for raw in json.loads(BASELINE_FILE.read_text()):
            b = CIBaseline(**raw)
            baselines[b.repo] = b

    scored: list[ScoredRepo] = []

    # --- Source 1: trivial_success repos from triage.json ---
    triage = [VerifiedRepo(**r) for r in json.loads(TRIAGE_FILE.read_text())]
    trivial = [v for v in triage if v.tag == "trivial_success" and v.accepted]
    print(f"[S6] {len(trivial)} trivial_success repos from S3")
    for v in trivial:
        baseline = baselines.get(v.repo)
        if baseline is None:
            print(f"  WARN: no baseline for {v.repo}, skipping")
            continue
        breakdown = _compute_breakdown(v, baseline)
        scored.append(ScoredRepo(
            repo=v.repo, sha=v.sha, source="trivial",
            setup_strategy=v.setup_strategy,
            setup_time_sec=v.setup_time_sec,
            mean_score=v.mean_score,
            difficulty=_trivial_label(breakdown.composite_score),
            solve_sh=v.setup_strategy,
            score_breakdown=breakdown,
        ))

    # --- Source 2: agent-solved repos from agent_results.json ---
    if AGENT_FILE.exists():
        agent_results = [AgentResult(**r) for r in json.loads(AGENT_FILE.read_text())]
        # Only include repos with at least one success
        solved = [r for r in agent_results if r.n_success > 0]
        print(f"[S6] {len(solved)} agent-solved repos from S5")
        already = {s.repo for s in scored}
        for r in solved:
            if r.repo in already:
                continue  # trivial_success takes precedence
            scored.append(ScoredRepo(
                repo=r.repo, sha=r.sha, source="agent",
                difficulty=r.difficulty,
                mean_score=r.pass_rate,
                solve_sh=r.best_solve_sh,
                frozen_requirements=r.frozen_requirements,
                oracle_pass_count=r.oracle_pass_count,
            ))

    # Print distribution
    print(f"[S6] Total: {len(scored)} repos")
    for label in ("easy", "medium", "hard", "very_hard"):
        n = sum(1 for s in scored if s.difficulty == label)
        if n:
            print(f"  {label}: {n} ({100*n/max(1,len(scored)):.0f}%)")

    # Stratified sample if we have more than target
    if len(scored) > target_size:
        print(f"[S6] Sampling {target_size} from {len(scored)} using stratified sampling")
        scored = _stratified_sample(scored, target_size, {
            "easy": diff_cfg["target_easy"],
            "medium": diff_cfg["target_medium"],
            "hard": diff_cfg["target_hard"],
        })

    OUTPUT_FILE.write_text(
        json.dumps([s.model_dump() for s in scored], indent=2, default=str)
    )
    print(f"[S6] Done. {len(scored)} scored repos saved → {OUTPUT_FILE}")
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description="S6: Difficulty scoring")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
