"""S4 · Infeasibility Pre-filter → data/agent_targets.json

Reads triage.json and keeps only needs_agent repos where the failure is
plausibly fixable by an agent. Infeasible repos (GPU, DinD, secrets, arch)
are filtered out before expensive agent calls.

Usage:
    python -m pipeline.steps.s4_prefilter
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import AgentTarget, CIBaseline, Candidate, VerifiedRepo

DATA_DIR = Path(__file__).parent.parent.parent / "data"
INPUT_TRIAGE = DATA_DIR / "triage.json"
INPUT_BASELINES = DATA_DIR / "ci_baselines.json"
INPUT_CANDIDATES = DATA_DIR / "candidates.json"
OUTPUT_FILE = DATA_DIR / "agent_targets.json"

# Patterns that indicate a failure is NOT fixable by an agent in a container
_INFEASIBLE_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)(cuda|nvcc|nvidia|flash.attn(?!-2)|gpu device|no cuda)", "gpu_required"),
    (r"(?i)(Cannot connect to the Docker daemon|docker.sock|dind)", "docker_in_docker"),
    (r"(?i)(arm-linux|aarch64-linux-gnu|cross.compil|target.*firmware)", "wrong_arch"),
    (r"(?i)(OPENAI_API_KEY|ANTHROPIC_API_KEY|AWS_ACCESS_KEY|API key.*required)", "secrets_required"),
    (r"(?i)(\.dll|\.exe|win32|windows.only)", "windows_only"),
    (r"(?i)(No such file.*\/dev\/|device.*not.*found.*\/dev\/)", "hardware_device"),
    (r"Connection refused.*localhost:(?:5432|3306|6379|9200)", "service_dependency"),
]

# Patterns that suggest the failure IS fixable (missing deps, wrong commands, etc.)
_FIXABLE_SIGNALS = [
    r"ModuleNotFoundError",
    r"No module named",
    r"ImportError",
    r"pip install",
    r"package.*not found",
    r"ERROR: Could not find",
    r"error: externally-managed-environment",
    r"command not found",
    r"No such file or directory",
]


def _classify_failure(failure_logs: dict[str, str]) -> tuple[bool, str]:
    """Return (is_infeasible, reason) for the combined failure logs."""
    combined = "\n".join(failure_logs.values())

    for pattern, reason in _INFEASIBLE_PATTERNS:
        if re.search(pattern, combined):
            return True, reason

    # If any fixable signal is present, lean toward keeping
    for signal in _FIXABLE_SIGNALS:
        if re.search(signal, combined):
            return False, "fixable_signal"

    # No strong signal either way — keep (let agent attempt)
    return False, "unknown"


def run() -> list[AgentTarget]:
    if not INPUT_TRIAGE.exists():
        print(f"[S4] ERROR: {INPUT_TRIAGE} not found — run S3 first")
        return []

    triage = [VerifiedRepo(**r) for r in json.loads(INPUT_TRIAGE.read_text())]
    needs_agent = [v for v in triage if v.tag == "needs_agent"]
    print(f"[S4] {len(triage)} triaged repos; {len(needs_agent)} tagged needs_agent")

    # Load CI baselines for expected_pass
    baseline_map: dict[str, CIBaseline] = {}
    if INPUT_BASELINES.exists():
        for raw in json.loads(INPUT_BASELINES.read_text()):
            b = CIBaseline(**raw)
            baseline_map[b.repo] = b

    # Load dep_file from candidates
    dep_file_map: dict[str, str] = {}
    if INPUT_CANDIDATES.exists():
        for raw in json.loads(INPUT_CANDIDATES.read_text()):
            c = Candidate(**raw)
            dep_file_map[c.repo] = c.dep_file

    targets: list[AgentTarget] = []
    filtered_infeasible = 0
    filtered_no_baseline = 0

    for v in needs_agent:
        baseline = baseline_map.get(v.repo)
        if not baseline:
            filtered_no_baseline += 1
            continue

        is_infeasible, reason = _classify_failure(v.failure_logs)

        target = AgentTarget(
            repo=v.repo,
            sha=v.sha,
            dep_file=dep_file_map.get(v.repo, "pyproject.toml"),
            expected_pass=baseline.expected_pass,
            failure_logs=v.failure_logs,
            infeasible_reason=reason if is_infeasible else None,
        )
        targets.append(target)
        print(f"  target: {v.repo} ({baseline.expected_pass} tests)")

        if is_infeasible:
            filtered_infeasible += 1

    # Save all targets (including infeasible_reason) — let S5 skip infeasible ones
    OUTPUT_FILE.write_text(
        json.dumps([t.model_dump() for t in targets], indent=2, default=str)
    )

    actionable = [t for t in targets if t.infeasible_reason is None]
    print(f"[S4] {len(targets)} agent targets written → {OUTPUT_FILE}")
    print(f"     actionable={len(actionable)}  pre-filtered-infeasible={filtered_infeasible}"
          f"  no-baseline={filtered_no_baseline}")
    return targets


def main() -> None:
    run()


if __name__ == "__main__":
    main()
