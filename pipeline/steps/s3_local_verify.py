"""S3 · Rule-based Triage → data/triage.json

For each CI-baseline repo, attempt all rule-based setup strategies.
Tags each repo as:
  trivial_success  — a rule-based strategy passed (score >= acceptance threshold)
  needs_agent      — all strategies failed; failure logs saved for S4/S5
  infeasible       — failure matches known-impossible patterns (GPU, DinD, etc.)

Usage:
    python -m pipeline.steps.s3_local_verify
    python -m pipeline.steps.s3_local_verify --workers 4
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import yaml

from ..docker_runner import DockerRunner
from ..models import CIBaseline, Candidate, VerifiedRepo
from ..strategies import get_strategy

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
INPUT_FILE = DATA_DIR / "ci_baselines.json"
CANDIDATES_FILE = DATA_DIR / "candidates.json"
OUTPUT_FILE = DATA_DIR / "triage.json"

# Patterns that indicate a setup failure is hardware/infra-infeasible
_INFEASIBLE_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)(cuda|nvcc|nvidia|flash.attn|gpu|device.*not.*found)", "gpu_required"),
    (r"(?i)(docker|dind|docker.in.docker|dockerd)", "docker_in_docker"),
    (r"(?i)(arm-linux|aarch64-linux-gnu|cross.compil|firmware)", "wrong_arch"),
    (r"(?i)(OPENAI_API_KEY|AWS_ACCESS_KEY|ANTHROPIC_API_KEY|API_KEY.*required)", "secrets_required"),
    (r"(?i)(\.dll|\.exe|win32|windows.only)", "windows_only"),
]


def _detect_infeasible(logs: dict[str, str]) -> Optional[str]:
    """Return infeasibility reason if any failure log matches a known-impossible pattern."""
    combined = "\n".join(logs.values())
    for pattern, reason in _INFEASIBLE_PATTERNS:
        if re.search(pattern, combined):
            return reason
    return None


def _build_image(runner: DockerRunner, strategy_name: str,
                 baseline: CIBaseline) -> str:
    """Build a Docker image for this repo and return its tag."""
    owner, name = baseline.repo.split("/", 1)
    # Docker image names: only lowercase alphanum, single/double underscore, hyphen, period
    safe_owner = owner.lower().replace("_", "-")
    safe_name = name.lower().replace("_", "-")
    tag = f"tb-verify/{safe_owner}-{safe_name}-{baseline.sha[:7]}"
    strategy = get_strategy(strategy_name)
    dockerfile = (
        strategy.dockerfile_base()
        + f"RUN git clone https://github.com/{owner}/{name}.git /app && "
        f"cd /app && (git checkout {baseline.sha} --quiet 2>/dev/null || "
        f"(git fetch --depth=1 origin {baseline.sha} && git checkout {baseline.sha} --quiet))\n"
        "WORKDIR /app\n"
    )
    runner.build_image(dockerfile, tag, timeout=600)
    return tag



def _single_run(runner: DockerRunner, image: str, baseline: CIBaseline,
                strategies: list[str], timeout: int,
                ) -> tuple[str | None, float, float, dict[str, str]]:
    """Attempt setup strategies then run tests in the SAME container.

    Returns (winning_cmd, score, elapsed, failure_logs).
    failure_logs maps strategy → last 100 lines of stdout (for failed strategies only).
    """
    lang_strategy = get_strategy("python")
    failure_logs: dict[str, str] = {}

    for setup_cmd in strategies:
        python_exe = lang_strategy.python_exe(setup_cmd)
        test_cmd = f"{python_exe} -m pytest --tb=no -q 2>&1"
        try:
            result = runner.run_commands(
                image,
                [setup_cmd, test_cmd],
                timeout=timeout,
                network_disabled=False,
            )
        except TimeoutError as exc:
            failure_logs[setup_cmd] = f"timeout: {exc}"
            continue
        counts = lang_strategy.parse_test_output(result["stdout"])
        if counts["passed"] > 0:
            score = min(1.0, counts["passed"] / max(1, baseline.expected_pass))
            return setup_cmd, score, result["elapsed_sec"], failure_logs
        # Capture last 100 lines for diagnosis
        tail = "\n".join(result["stdout"].splitlines()[-100:])
        failure_logs[setup_cmd] = tail

    return None, 0.0, 0.0, failure_logs


def _verify_repo(baseline: CIBaseline, dep_file: str, config: dict) -> VerifiedRepo:
    """Run N independent container verification passes for a repo.

    Tags result as trivial_success / needs_agent / infeasible.
    """
    ver_cfg = config["verification"]
    n_runs = ver_cfg["runs_per_repo"]
    accept_score = ver_cfg["acceptance_score"]
    accept_stdev = ver_cfg["acceptance_stdev"]
    timeout = ver_cfg["container_timeout_sec"]

    strategy = get_strategy("python")
    strategies = strategy.setup_strategies(dep_file)

    runner = DockerRunner()

    try:
        image = _build_image(runner, "python", baseline)
    except Exception as exc:
        return VerifiedRepo(
            repo=baseline.repo,
            sha=baseline.sha,
            tag="needs_agent",
            setup_strategy="",
            setup_time_sec=0.0,
            scores=[],
            mean_score=0.0,
            accepted=False,
            rejection_reason=f"docker_build_failed: {exc}",
            failure_logs={"docker_build": str(exc)},
        )

    scores: list[float] = []
    winning_cmd = None
    total_setup_time = 0.0
    all_failure_logs: dict[str, str] = {}

    try:
        for run_idx in range(n_runs):
            cmd, score, elapsed, failure_logs = _single_run(
                runner, image, baseline, strategies, timeout
            )
            scores.append(score)
            total_setup_time += elapsed
            if winning_cmd is None and cmd:
                winning_cmd = cmd
            # Merge failure logs (first run's logs are most diagnostic)
            if run_idx == 0:
                all_failure_logs = failure_logs
    finally:
        runner.remove_image(image, force=True)

    if not scores:
        return VerifiedRepo(
            repo=baseline.repo, sha=baseline.sha,
            tag="needs_agent",
            setup_strategy="", setup_time_sec=0.0, scores=[], mean_score=0.0,
            accepted=False, rejection_reason="no_runs_completed",
            failure_logs=all_failure_logs,
        )

    mean = sum(scores) / len(scores)
    stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0

    trivial_pass = (
        winning_cmd is not None
        and mean >= accept_score
        and stdev < accept_stdev
    )

    if trivial_pass:
        tag = "trivial_success"
        reason = None
    else:
        # Check if failure is infeasible
        infeasible_reason = _detect_infeasible(all_failure_logs)
        if infeasible_reason:
            tag = "infeasible"
            reason = infeasible_reason
        elif winning_cmd is not None:
            # Setup ran but score too low or too flaky
            tag = "needs_agent"
            reason = (f"score_too_low: mean={mean:.3f}" if mean < accept_score
                      else f"flaky_tests: stdev={stdev:.3f}")
        else:
            tag = "needs_agent"
            reason = "setup_failed"

    return VerifiedRepo(
        repo=baseline.repo,
        sha=baseline.sha,
        tag=tag,
        setup_strategy=winning_cmd or "",
        setup_time_sec=round(total_setup_time / len(scores), 1),
        scores=scores,
        mean_score=round(mean, 4),
        accepted=trivial_pass,
        rejection_reason=reason,
        failure_logs={} if trivial_pass else all_failure_logs,
    )


def run(workers: int | None = None) -> list[VerifiedRepo]:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    import os
    default_workers = min(8, max(1, os.cpu_count() // 2))
    workers = workers or config["verification"].get("parallel_containers", default_workers)

    if not INPUT_FILE.exists():
        print(f"[S3] ERROR: {INPUT_FILE} not found — run S2 first")
        return []

    baselines = [CIBaseline(**r) for r in json.loads(INPUT_FILE.read_text())]
    print(f"[S3] Verifying {len(baselines)} repos with {workers} parallel workers")

    # Load dep_file from candidates for strategy selection
    dep_file_map: dict[str, str] = {}
    if CANDIDATES_FILE.exists():
        for raw in json.loads(CANDIDATES_FILE.read_text()):
            c = Candidate(**raw)
            dep_file_map[c.repo] = c.dep_file

    # Load existing (idempotent)
    existing: dict[str, VerifiedRepo] = {}
    if OUTPUT_FILE.exists():
        for raw in json.loads(OUTPUT_FILE.read_text()):
            v = VerifiedRepo(**raw)
            existing[v.repo] = v
        print(f"[S3] Resuming — {len(existing)} repos already verified")

    to_process = [b for b in baselines if b.repo not in existing]
    verified: dict[str, VerifiedRepo] = dict(existing)

    def _process(baseline: CIBaseline) -> VerifiedRepo:
        dep_file = dep_file_map.get(baseline.repo, "pyproject.toml")
        print(f"  Triaging {baseline.repo} (dep_file={dep_file}) …")
        result = _verify_repo(baseline, dep_file, config)
        tag_sym = {"trivial_success": "✓", "needs_agent": "~", "infeasible": "✗"}.get(result.tag, "?")
        print(f"  [{tag_sym}] {result.repo} tag={result.tag} "
              f"scores={result.scores} reason={result.rejection_reason or 'ok'}")
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process, b): b for b in to_process}
        for fut in as_completed(futures):
            result = fut.result()
            verified[result.repo] = result
            # Save incrementally
            OUTPUT_FILE.write_text(
                json.dumps([v.model_dump() for v in verified.values()],
                           indent=2, default=str)
            )

    trivial = sum(1 for v in verified.values() if v.tag == "trivial_success")
    needs_agent = sum(1 for v in verified.values() if v.tag == "needs_agent")
    infeasible = sum(1 for v in verified.values() if v.tag == "infeasible")
    print(f"\n[S3] Done. {len(verified)} repos triaged → {OUTPUT_FILE}")
    print(f"     trivial_success={trivial}  needs_agent={needs_agent}  infeasible={infeasible}")
    return list(verified.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="S3: Local Docker verification")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    run(workers=args.workers)


if __name__ == "__main__":
    main()
