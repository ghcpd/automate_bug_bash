"""S2 · CI Baseline Extraction → data/ci_baselines.json

Usage:
    python -m pipeline.steps.s2_ci_baseline
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..github_client import GitHubClient
from ..models import CIBaseline, CIJobResult, Candidate

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
INPUT_FILE = DATA_DIR / "candidates.json"
OUTPUT_FILE = DATA_DIR / "ci_baselines.json"

# Pytest summary patterns
_PASSED_RE = re.compile(r"(\d+) passed")
_FAILED_RE = re.compile(r"(\d+) failed")
_ERROR_RE = re.compile(r"(\d+) error")
_SKIPPED_RE = re.compile(r"(\d+) skipped")
_DURATION_RE = re.compile(r"in\s+([\d.]+)s")


def _parse_pytest_summary(log_text: str) -> dict[str, int] | None:
    """Extract pass/fail/error counts from pytest log text."""
    for line in reversed(log_text.splitlines()):
        m_pass = _PASSED_RE.search(line)
        if not m_pass:
            continue
        passed = int(m_pass.group(1))
        m_fail = _FAILED_RE.search(line)
        m_err = _ERROR_RE.search(line)
        return {
            "passed": passed,
            "failed": int(m_fail.group(1)) if m_fail else 0,
            "error": int(m_err.group(1)) if m_err else 0,
        }
    return None


def _parse_job_results(job_id: int, job_name: str,
                       log_text: str) -> list[CIJobResult]:
    """Extract all distinct pytest runs from a single job's log.

    A job may run pytest multiple times (e.g. unit then integration tests as
    separate steps). Each distinct (passed, failed, errors, skipped) tuple
    becomes a separate CIJobResult so S5 can oracle-match any one of them.
    """
    results: list[CIJobResult] = []
    seen: set[tuple] = set()
    for line in log_text.splitlines():
        m_pass = _PASSED_RE.search(line)
        if not m_pass:
            continue
        passed = int(m_pass.group(1))
        m_fail = _FAILED_RE.search(line)
        m_err = _ERROR_RE.search(line)
        m_skip = _SKIPPED_RE.search(line)
        failed  = int(m_fail.group(1)) if m_fail else 0
        errors  = int(m_err.group(1))  if m_err  else 0
        skipped = int(m_skip.group(1)) if m_skip else 0
        key = (passed, failed, errors, skipped)
        if key not in seen:
            seen.add(key)
            results.append(CIJobResult(
                job_id=job_id, job_name=job_name,
                passed=passed, failed=failed, errors=errors, skipped=skipped,
            ))
    return results


def _extract_ci_duration(run: dict) -> int | None:
    """Return CI run duration in seconds, or None."""
    created = run.get("created_at")
    updated = run.get("updated_at")
    if created and updated:
        try:
            fmt = "%Y-%m-%dT%H:%M:%SZ"
            dt_c = datetime.strptime(created, fmt).replace(tzinfo=timezone.utc)
            dt_u = datetime.strptime(updated, fmt).replace(tzinfo=timezone.utc)
            return int((dt_u - dt_c).total_seconds())
        except Exception:
            pass
    return None


def _find_baseline(client: GitHubClient, repo: str,
                   max_ci_duration: int) -> CIBaseline | None:
    """Find the most recent successful Actions run with parseable pytest logs.

    Stores individual CIJobResult entries (one per distinct pytest run per job)
    rather than aggregating, so S5 can oracle-match against any single run.
    expected_pass = max(job.passed) for backward compat with S3/S4 thresholds.
    """
    owner, name = repo.split("/", 1)

    runs = client.list_workflow_runs(owner, name, status="success", per_page=5)
    if not runs:
        return None

    for run in runs:
        duration = _extract_ci_duration(run)
        if duration and duration > max_ci_duration:
            continue

        run_id = run["id"]
        sha = run.get("head_sha", "")

        jobs = client.list_jobs(owner, name, run_id)
        # Prefer jobs whose name contains "test"
        test_jobs = [j for j in jobs
                     if "test" in j.get("name", "").lower()
                     and j.get("conclusion") == "success"]
        if not test_jobs:
            test_jobs = [j for j in jobs if j.get("conclusion") == "success"]
        if not test_jobs:
            continue

        # Collect per-job results — one CIJobResult per distinct pytest run.
        all_job_results: list[CIJobResult] = []
        best_job_id = test_jobs[0]["id"]
        best_job_passed = 0

        for job in test_jobs:
            try:
                log = client.get_job_logs(owner, name, job["id"])
            except Exception:
                continue
            job_results = _parse_job_results(job["id"], job.get("name", ""), log)
            all_job_results.extend(job_results)
            for r in job_results:
                if r.passed > best_job_passed:
                    best_job_passed = r.passed
                    best_job_id = job["id"]

        if not all_job_results:
            continue

        expected_pass = max(r.passed for r in all_job_results)
        expected_fail = sum(r.failed for r in all_job_results
                            if r.job_id == best_job_id)
        expected_error = sum(r.errors for r in all_job_results
                             if r.job_id == best_job_id)

        return CIBaseline(
            repo=repo,
            sha=sha,
            workflow_run_id=run_id,
            job_id=best_job_id,
            expected_pass=expected_pass,
            expected_fail=expected_fail,
            expected_error=expected_error,
            ci_duration_sec=duration,
            parsed_at=datetime.now(timezone.utc),
            job_results=all_job_results,
        )
    return None


def run(max_repos: int | None = None) -> list[CIBaseline]:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    max_ci_duration = config["filters"]["max_ci_duration_sec"]

    if not INPUT_FILE.exists():
        print(f"[S2] ERROR: {INPUT_FILE} not found — run S1 first")
        return []

    candidates = [Candidate(**r) for r in json.loads(INPUT_FILE.read_text())]
    if max_repos:
        candidates = candidates[:max_repos]
    print(f"[S2] Processing {len(candidates)} candidates")

    # Load existing baselines (idempotent)
    existing: dict[str, CIBaseline] = {}
    if OUTPUT_FILE.exists():
        for raw in json.loads(OUTPUT_FILE.read_text()):
            b = CIBaseline(**raw)
            existing[b.repo] = b
        print(f"[S2] Resuming — {len(existing)} baselines already saved")

    client = GitHubClient()
    baselines = dict(existing)
    discarded = 0
    processed = 0

    for candidate in candidates:
        if candidate.repo in baselines:
            continue
        processed += 1
        print(f"  [{processed}] {candidate.repo} …", end=" ", flush=True)
        try:
            baseline = _find_baseline(client, candidate.repo, max_ci_duration)
        except Exception as exc:
            discarded += 1
            print(f"✗ skipped ({type(exc).__name__}: {exc})")
            continue
        if baseline:
            baselines[baseline.repo] = baseline
            print(f"✓ {baseline.expected_pass} passed")
        else:
            discarded += 1
            print("✗ no parseable baseline")

        # Save incrementally every 10 repos
        if processed % 10 == 0:
            OUTPUT_FILE.write_text(
                json.dumps([b.model_dump() for b in baselines.values()],
                           indent=2, default=str)
            )

    baseline_list = list(baselines.values())
    OUTPUT_FILE.write_text(
        json.dumps([b.model_dump() for b in baseline_list], indent=2, default=str)
    )
    print(f"\n[S2] Done. {len(baseline_list)} baselines saved "
          f"({discarded} discarded). → {OUTPUT_FILE}")
    return baseline_list


def main() -> None:
    parser = argparse.ArgumentParser(description="S2: CI baseline extraction")
    parser.add_argument("--max", type=int, default=None,
                        help="Process only first N candidates (for testing)")
    args = parser.parse_args()
    run(max_repos=args.max)


if __name__ == "__main__":
    main()
