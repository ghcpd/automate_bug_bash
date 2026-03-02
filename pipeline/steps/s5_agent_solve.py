"""S5 · Agent-based Multi-rollout Solve → data/agent_results.json

For each actionable agent_target:
  1. Build a Docker image (clone only, no setup) via s3's _build_image logic
  2. Run N independent agent rollouts, each in a fresh container:
     - Start isolated container from the image
     - Launch `copilot -p <prompt>` — agent drives setup via docker exec
     - Verify result: run pytest inside container, parse score
     - Capture copilot stdout as trajectory
  3. Record every rollout — success and failure alike (both are SFT training data)
  4. Aggregate per-repo: pass_rate → difficulty, extract best_solve_sh

Difficulty is inferred from pass_rate across N rollouts:
  >= 0.80 → easy | 0.30–0.80 → medium | 0.05–0.30 → hard | < 0.05 → very_hard

Usage:
    python -m pipeline.steps.s5_agent_solve
    python -m pipeline.steps.s5_agent_solve --n-rollouts 3
    python -m pipeline.steps.s5_agent_solve --dry-run     # build images only
    python -m pipeline.steps.s5_agent_solve --repo owner/name  # single repo
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import textwrap
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..docker_runner import DockerRunner
from ..models import AgentResult, AgentRollout, AgentTarget, CIBaseline
from ..steps.s3_local_verify import _build_image
DATA_DIR = Path(__file__).parent.parent.parent / "data"
INPUT_FILE = DATA_DIR / "agent_targets.json"
BASELINES_FILE = DATA_DIR / "ci_baselines.json"
OUTPUT_FILE = DATA_DIR / "agent_results.json"
TRACES_DIR = DATA_DIR / "traces"

# Difficulty thresholds based on pass_rate across rollouts
_DIFFICULTY_THRESHOLDS = [
    (0.80, "easy"),
    (0.30, "medium"),
    (0.05, "hard"),
    (0.00, "very_hard"),
]


def _difficulty_from_rate(pass_rate: float) -> str:
    for threshold, label in _DIFFICULTY_THRESHOLDS:
        if pass_rate >= threshold:
            return label
    return "very_hard"


def _container_name(target: AgentTarget, rollout_id: int) -> str:
    safe = target.repo.replace("/", "-").replace("_", "-").lower()
    return f"tb-s5-{safe}-r{rollout_id}"


def _build_prompt(target: AgentTarget, container_name: str,
                  expected_pass: int) -> str:
    """Build the copilot -p prompt for one rollout."""
    owner, name = target.repo.split("/", 1)

    # Summarise what the rule-based attempts already tried and failed
    prior_attempts = ""
    if target.failure_logs:
        lines = []
        for cmd, log in list(target.failure_logs.items())[:3]:
            short_cmd = cmd[:80]
            last_err = [l for l in log.splitlines() if l.strip()][-3:]
            lines.append(f"  Command tried: {short_cmd}")
            lines.append("  Last output:\n" + "\n".join(f"    {l}" for l in last_err))
        prior_attempts = "Prior rule-based attempts (all failed):\n" + "\n".join(lines)

    return textwrap.dedent(f"""\
        You are a developer setting up a Python project's dev environment inside a Docker container.

        Container name: {container_name}
        Repo: {owner}/{name}
        Dependency file: {target.dep_file}
        Expected passing tests (CI baseline): {expected_pass}

        The repo is already cloned at /app inside the container.
        No dependencies have been installed yet.

        {prior_attempts}

        Your goal: install all dependencies so that `python -m pytest --tb=no -q` passes
        with at least {int(expected_pass * 0.95)} tests passing.

        Rules:
        - Use `docker exec {container_name} bash -c "..."` for ALL commands inside the container.
        - Do NOT modify any test files (files matching test_*.py or *_test.py).
        - The container has `uv` available. Prefer uv over pip.
        - If a venv is needed, use `/opt/venv` (uv venv /opt/venv) unless uv sync creates .venv.
        - Pin exact package versions in the final solve.sh using `uv pip freeze`.

        When you have confirmed that pytest passes (score >= 0.95), write the complete
        solution as a bash script to /tmp/{container_name}_solve.sh on the HOST (not inside
        the container). The script must be self-contained and reproducible from a fresh
        clone — it should only contain the install commands, not the pytest run itself.

        Start by inspecting the repo structure and dependency file, then install.
    """).strip()


def _run_container(image: str, container_name: str, timeout_sec: int) -> bool:
    """Start a detached container. Returns True on success."""
    # Remove any leftover container with the same name (e.g. from a crashed prior run)
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
    result = subprocess.run(
        ["docker", "run", "-d", "--name", container_name, image,
         "sleep", str(timeout_sec + 120)],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _stop_container(container_name: str) -> None:
    try:
        subprocess.run(["docker", "stop", "--time=5", container_name],
                       capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", container_name], capture_output=True)
    try:
        subprocess.run(["docker", "rm", "-f", container_name],
                       capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        # Kill first, then retry rm
        subprocess.run(["docker", "kill", container_name], capture_output=True)
        try:
            subprocess.run(["docker", "rm", "-f", container_name],
                           capture_output=True, timeout=30)
        except Exception:
            pass
    except Exception:
        pass


# Unit-test subdirectory candidates tried in order before falling back to the
# whole project, to avoid integration tests that require external services.
_UNIT_TEST_PATHS = ["tests/unit", "test/unit", "unit_tests", "tests", "test", ""]

# Matches `python -m pytest <args>` in a script line.
_PYTEST_LINE_RE = re.compile(r"python\s+-m\s+pytest\s+([^\n\"']+)")


def _build_verify_script(solve_sh: str, xml_path: str) -> str:
    """Build a lightweight verification bash script from solve.sh.

    Does NOT re-run install steps (they are already done by the agent).
    Only extracts:
      1. ``export VAR=value`` lines — preserves runtime env vars like DISPLAY
      2. The last pytest invocation with ``--junit-xml`` injected, or a generic
         subdirectory scan if solve.sh has no pytest call.

    This ensures env vars set up by the agent (e.g. DISPLAY=:99 for Xvfb) are
    active when pytest runs, without re-running potentially non-idempotent setup.
    """
    # Collect export lines (e.g. export DISPLAY=:99)
    exports = [
        line.strip()
        for line in solve_sh.splitlines()
        if line.strip().startswith("export ") and "=" in line
    ]

    # Find the last pytest invocation in solve.sh
    matches = list(_PYTEST_LINE_RE.finditer(solve_sh))
    if matches:
        pytest_line = matches[-1].group(0)
        # Strip trailing output redirections
        pytest_line = re.sub(r'\s*2?>&?\d*\s*\|.*$', '', pytest_line).strip()
        # Strip --tb=... and bare -q; we add our own
        pytest_line = re.sub(r'--tb=\S+', '', pytest_line)
        pytest_line = re.sub(r'(?<!\w)-q\b', '', pytest_line)
        pytest_cmd = (f"{pytest_line.rstrip()} --tb=no -q "
                      f"--continue-on-collection-errors --junit-xml={xml_path}")
    else:
        # No pytest call in solve.sh — generic subdirectory scan.
        paths_expr = " ".join(f'"{p}"' for p in _UNIT_TEST_PATHS)
        pytest_cmd = textwrap.dedent(f"""\
            if [ -x /app/.venv/bin/python ]; then _PY=/app/.venv/bin/python
            elif [ -x /opt/venv/bin/python ]; then _PY=/opt/venv/bin/python
            else _PY=python3; fi
            for _TPATH in {paths_expr}; do
              if [ -z "$_TPATH" ] || [ -d "$_TPATH" ]; then
                $_PY -m pytest "$_TPATH" --tb=no -q \\
                  --continue-on-collection-errors \\
                  --junit-xml={xml_path}
                break
              fi
            done""")

    parts = ["cd /app"] + exports + [pytest_cmd]
    return "\n".join(parts)


def _verify_in_container(container_name: str,
                          solve_sh: str = "",
                          timeout: int = 600) -> dict:
    """Run pytest inside *container_name* and return JUnit XML counts.

    If *solve_sh* is provided, runs a lightweight script that:
    - Applies env vars from solve.sh (e.g. DISPLAY=:99 for Xvfb-dependent tests)
    - Reuses the agent's pytest invocation flags (or generic scan if none)
    Without re-running install steps that are already done by the agent.

    Falls back to a generic docker exec command when no solve.sh is available.

    Returns a dict with keys: passed, total, failures, errors, skipped.
    """
    xml_path_in_container = "/tmp/pytest_results.xml"
    xml_path_on_host = Path(f"/tmp/{container_name}_junit.xml")

    _empty = {"passed": 0, "total": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        if solve_sh:
            cmd = _build_verify_script(solve_sh, xml_path_in_container)
        else:
            # Generic fallback: try unit-test subdirectories in order.
            paths_expr = " ".join(f'"{p}"' for p in _UNIT_TEST_PATHS)
            cmd = textwrap.dedent(f"""\
                cd /app
                if [ -x /app/.venv/bin/python ]; then PY=/app/.venv/bin/python
                elif [ -x /opt/venv/bin/python ]; then PY=/opt/venv/bin/python
                else PY=python3; fi
                for TPATH in {paths_expr}; do
                  if [ -z "$TPATH" ] || [ -d "$TPATH" ]; then
                    $PY -m pytest $TPATH --tb=no -q \\
                      --continue-on-collection-errors \\
                      --junit-xml={xml_path_in_container} 2>&1 | tail -1
                    exit 0
                  fi
                done
            """)

        subprocess.run(
            ["docker", "exec", container_name, "bash", "-c", cmd],
            capture_output=True, text=True, timeout=timeout,
        )

        cp = subprocess.run(
            ["docker", "cp", f"{container_name}:{xml_path_in_container}",
             str(xml_path_on_host)],
            capture_output=True,
        )
        if cp.returncode != 0 or not xml_path_on_host.exists():
            return _empty

        tree = ET.parse(xml_path_on_host)
        root = tree.getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is None:
            return _empty
        total    = int(suite.attrib.get("tests",    0))
        failures = int(suite.attrib.get("failures", 0))
        errors   = int(suite.attrib.get("errors",   0))
        skipped  = int(suite.attrib.get("skipped",  0))
        passed   = max(0, total - failures - errors - skipped)
        return {"passed": passed, "total": total,
                "failures": failures, "errors": errors, "skipped": skipped}

    except (subprocess.TimeoutExpired, ET.ParseError, KeyError, ValueError):
        return _empty
    finally:
        xml_path_on_host.unlink(missing_ok=True)


def _find_oracle_match(agent: dict, job_results: list):
    """Return the best matching CIJobResult, or None if no match.

    Criteria:
    - agent.passed >= CI_job.passed * 0.95 (one-sided — agent may run more tests)
    - errors <= 5% of total (small error ratio tolerated for pre-existing setup
      errors; strict zero would reject repos where a few fixtures always fail)
    - total > 0

    Failures are fully tolerated — they represent pre-existing code failures,
    not a broken dev environment.

    Returns the highest-passed CI job that the agent meets the threshold for.
    """
    if agent["total"] == 0:
        return None
    # Tolerate up to 5% errors (pre-existing fixture/teardown errors)
    if agent["errors"] > max(2, 0.05 * agent["total"]):
        return None
    best = None
    best_passed = -1
    for job in job_results:
        threshold = max(1, job.passed * 0.95)
        if agent["passed"] >= threshold and job.passed > best_passed:
            best_passed = job.passed
            best = job
    return best


_MAX_STEPS_DEFAULT = 50
# Copilot emits a "● <tool name>" line at the start of each tool call.
_STEP_RE = re.compile(r"^[●•] ")


def _run_copilot(cmd: list[str], trace_path: Path,
                 max_steps: int, wall_timeout: int) -> tuple[int, str, str]:
    """Run copilot subprocess, streaming stdout line-by-line.

    Terminates early if the agent exceeds *max_steps* tool calls.
    *wall_timeout* is a hard ceiling in seconds in case a single step hangs.

    Returns (returncode, trajectory_text, failure_reason_or_empty).
    """
    import signal, threading

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, bufsize=1,
    )

    lines: list[str] = []
    step_count = 0
    terminated_reason = ""

    # Wall-clock watchdog: kills process if it hangs for wall_timeout seconds.
    def _watchdog():
        try:
            proc.wait(timeout=wall_timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()

    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()

    try:
        for line in proc.stdout:
            lines.append(line)
            if _STEP_RE.match(line):
                step_count += 1
                if step_count >= max_steps:
                    terminated_reason = f"max_steps({max_steps})"
                    proc.terminate()
                    # Drain remaining buffered output
                    for tail in proc.stdout:
                        lines.append(tail)
                    break
    finally:
        proc.stdout.close()
        proc.wait()

    trajectory = "".join(lines)
    if terminated_reason:
        trajectory = f"[TERMINATED: {terminated_reason} after {step_count} steps]\n" + trajectory
    trace_path.write_text(trajectory, encoding="utf-8")

    rc = proc.returncode if not terminated_reason else -1
    return rc, trajectory, terminated_reason


def _run_rollout(target: AgentTarget, image: str, rollout_id: int,
                 expected_pass: int, timeout: int = 900,
                 max_steps: int = _MAX_STEPS_DEFAULT,
                 model: str = "") -> dict:
    """Run one copilot-p rollout against a live container. Returns result dict."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    cname = _container_name(target, rollout_id)
    trace_path = TRACES_DIR / f"{cname}.txt"
    solve_sh_host = Path(f"/tmp/{cname}_solve.sh")

    # Start fresh container
    _empty_verify = {"passed": 0, "total": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not _run_container(image, cname, timeout):
        return {"verify": _empty_verify, "returncode": -1,
                "trace_path": str(trace_path),
                "failure_reason": "container_start_failed", "solve_sh": ""}

    try:
        prompt = _build_prompt(target, cname, expected_pass)

        cmd = ["copilot", "--allow-all", "-p", prompt]
        if model:
            cmd += ["--model", model]

        returncode, trajectory, term_reason = _run_copilot(
            cmd, trace_path, max_steps=max_steps, wall_timeout=timeout,
        )

        # Read solve.sh before verification so we can reuse its pytest flags.
        solve_sh = ""
        if solve_sh_host.exists():
            solve_sh = solve_sh_host.read_text()
            solve_sh_host.unlink(missing_ok=True)

        # Independent verification using the agent's own pytest invocation
        # (extracted from solve.sh) so repo-specific flags are honoured.
        verify = _verify_in_container(cname, solve_sh=solve_sh)

        if not solve_sh and verify["passed"] > 0:
            # Agent succeeded but didn't write solve.sh — extract from trajectory.
            solve_sh = _extract_solve_sh_from_trajectory(trajectory, cname)

        # Capture pip freeze after verification so we get the final installed state.
        frozen_requirements = ""
        if verify["passed"] > 0:
            frozen_requirements = _capture_frozen_requirements(cname)

        failure_reason = term_reason if term_reason else None
        return {
            "verify": verify,
            "returncode": returncode,
            "trace_path": str(trace_path),
            "failure_reason": failure_reason,
            "solve_sh": solve_sh,
            "frozen_requirements": frozen_requirements,
        }

    except Exception as exc:
        trace_path.write_text(f"[ERROR] {exc}\n", encoding="utf-8")
        return {"verify": _empty_verify, "returncode": -1,
                "trace_path": str(trace_path),
                "failure_reason": f"exception: {type(exc).__name__}",
                "solve_sh": "", "frozen_requirements": ""}
    finally:
        _stop_container(cname)


def _capture_frozen_requirements(container_name: str) -> str:
    """Run uv pip freeze inside the container and return the output."""
    # uv doesn't install a pip binary; use `uv pip freeze --python <exe>`
    for python_exe in ("/opt/venv/bin/python", "/app/.venv/bin/python", "python3"):
        result = subprocess.run(
            ["docker", "exec", container_name, "uv", "pip", "freeze", "--python", python_exe],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return ""


def _extract_solve_sh_from_trajectory(trajectory: str, container_name: str) -> str:
    """Extract docker exec commands from copilot output and build a solve.sh."""
    # Find all `docker exec <container> bash -c "..."` calls in the trajectory
    pattern = rf'docker exec {re.escape(container_name)} bash -c "([^"]+)"'
    cmds = re.findall(pattern, trajectory)
    # Also catch single-quoted variants
    pattern_sq = rf"docker exec {re.escape(container_name)} bash -c '([^']+)'"
    cmds += re.findall(pattern_sq, trajectory)

    if not cmds:
        return ""

    lines = ["#!/bin/bash", "# Auto-extracted from copilot trajectory", "set -e", "cd /app", ""]
    lines += cmds
    return "\n".join(lines) + "\n"


def _build_image_for_target(target: AgentTarget,
                             baseline_map: dict[str, CIBaseline]) -> str | None:
    """Build Docker image for a target. Returns image tag or None on failure."""
    baseline = baseline_map.get(target.repo)
    if not baseline:
        return None
    runner = DockerRunner()
    try:
        return _build_image(runner, "python", baseline)
    except Exception as exc:
        print(f"  [build-failed] {target.repo}: {exc}")
        return None


def _process_target(target: AgentTarget, baseline_map: dict[str, CIBaseline],
                    n_rollouts: int, dry_run: bool = False,
                    existing_result: AgentResult | None = None,
                    model: str = "", early_stop: bool = False,
                    max_steps: int = _MAX_STEPS_DEFAULT) -> AgentResult:
    """Build image + run rollouts for one target, resuming from existing_result."""
    existing_rollouts: list[AgentRollout] = (
        existing_result.rollouts if existing_result and existing_result.rollouts else []
    )
    already_done = len(existing_rollouts)
    remaining = n_rollouts - already_done
    if remaining <= 0:
        return existing_result  # type: ignore[return-value]

    image = _build_image_for_target(target, baseline_map)
    if image is None:
        return AgentResult(
            repo=target.repo, sha=target.sha,
            n_rollouts=already_done, n_success=sum(1 for r in existing_rollouts if r.success),
            pass_rate=0.0, difficulty="very_hard", rollouts=existing_rollouts,
        )

    if dry_run:
        print(f"  [dry-run] image={image}")
        return AgentResult(
            repo=target.repo, sha=target.sha,
            n_rollouts=already_done, n_success=0, pass_rate=0.0, difficulty="unknown",
            rollouts=existing_rollouts,
        )

    expected_pass = target.expected_pass
    new_rollouts: list[AgentRollout] = []

    # CI job results for oracle matching (may be empty for old baselines)
    baseline = baseline_map.get(target.repo)
    ci_job_results = baseline.job_results if baseline else []

    # Track oracle pass count; seed from any prior successful rollouts if resuming.
    oracle_pass_count: int = existing_result.oracle_pass_count if existing_result else 0

    for i in range(already_done, already_done + remaining):
        raw = _run_rollout(target, image, rollout_id=i,
                           expected_pass=expected_pass, model=model,
                           max_steps=max_steps)
        verify = raw["verify"]
        passed_count  = verify["passed"]
        total_count   = verify["total"]
        failures_count = verify["failures"]
        errors_count  = verify["errors"]

        # Success: env set up correctly.
        # Clean run: no failures, no errors, at least one test collected.
        # Oracle match: passed count matches a CI job (failures tolerated —
        #   pre-existing test failures don't indicate a broken environment).
        matched_job = (
            _find_oracle_match(verify, ci_job_results)
            if ci_job_results
            else None
        )
        is_oracle_quality = (
            matched_job is not None
            if ci_job_results
            else (errors_count == 0 and failures_count == 0 and total_count > 0
                  and passed_count >= 0.95 * expected_pass)  # fallback for old baselines
        )
        clean_run = (failures_count == 0 and errors_count == 0 and total_count > 0)
        success = clean_run or is_oracle_quality

        # Oracle calibration: use matched CI job's passed count when available
        # (more accurate than raw passed_count when there are pre-existing failures).
        if success:
            ref_count = matched_job.passed if matched_job else passed_count
            oracle_pass_count = max(oracle_pass_count, ref_count)

        # Score relative to best oracle seen; fall back to CI expected if none yet.
        denom = oracle_pass_count if oracle_pass_count > 0 else max(1, expected_pass)
        score = min(1.0, passed_count / denom)

        # Display denominator: matched CI job's passed count when available, else total_count.
        display_denom = matched_job.passed if matched_job else total_count
        failure_reason = raw["failure_reason"] or (None if success else "no_clean_run")
        print(f"  [{target.repo}] rollout {i+1}/{n_rollouts} … "
              f"passed={passed_count}/{display_denom} score={score:.3f} oracle={oracle_pass_count} "
              f"{'✓' if success else '✗'} ({failure_reason or 'ok'})"
              + (" [oracle-match]" if is_oracle_quality else ""))
        new_rollouts.append(AgentRollout(
            repo=target.repo, sha=target.sha, rollout_id=i,
            score=score, success=success,
            passed_count=passed_count,
            total_count=total_count,
            failures_count=failures_count,
            errors_count=errors_count,
            trajectory_path=raw["trace_path"],
            solve_sh=raw["solve_sh"],
            frozen_requirements=raw["frozen_requirements"],
            failure_reason=failure_reason,
            model=model,
        ))

        # Early stop if an oracle-quality solution was found.
        if early_stop and is_oracle_quality:
            break

    # Post-hoc rescore all new rollouts against the final oracle denominator.
    denom = oracle_pass_count if oracle_pass_count > 0 else max(1, expected_pass)
    for r in new_rollouts:
        r.score = round(min(1.0, r.passed_count / denom), 4)

    all_rollouts = existing_rollouts + new_rollouts
    n_success = sum(1 for r in all_rollouts if r.success)
    total = len(all_rollouts)
    pass_rate = n_success / total
    best = max((r for r in all_rollouts if r.success), key=lambda r: r.score, default=None)

    return AgentResult(
        repo=target.repo, sha=target.sha,
        n_rollouts=total, n_success=n_success,
        pass_rate=round(pass_rate, 3),
        difficulty=_difficulty_from_rate(pass_rate),
        best_solve_sh=best.solve_sh if best else "",
        frozen_requirements=best.frozen_requirements if best else "",
        oracle_pass_count=oracle_pass_count,
        rollouts=all_rollouts,
    )


def run(n_rollouts: int = 10, dry_run: bool = False,
        repo_filter: str | None = None, model: str = "",
        workers: int = 4, early_stop: bool = False,
        max_steps: int = _MAX_STEPS_DEFAULT,
        max_repos: int | None = None,
        start_index: int = 0,
        end_index: int | None = None) -> list[AgentResult]:
    if not INPUT_FILE.exists():
        print(f"[S5] ERROR: {INPUT_FILE} not found — run S4 first")
        return []

    all_targets = [AgentTarget(**r) for r in json.loads(INPUT_FILE.read_text())]
    targets = [t for t in all_targets if t.infeasible_reason is None]
    if repo_filter:
        targets = [t for t in targets if t.repo == repo_filter]
    targets = targets[start_index:end_index]
    if max_repos is not None:
        targets = targets[:max_repos]

    # Load CI baselines (needed for image building)
    baseline_map: dict[str, CIBaseline] = {}
    if BASELINES_FILE.exists():
        for raw in json.loads(BASELINES_FILE.read_text()):
            b = CIBaseline(**raw)
            baseline_map[b.repo] = b

    model_tag = f" model={model}" if model else ""
    early_tag = " early-stop" if early_stop else ""
    print(f"[S5] {len(targets)} actionable targets; n_rollouts={n_rollouts}{model_tag}"
          f" workers={workers} max_steps={max_steps}{early_tag}{' [dry-run]' if dry_run else ''}")

    # Load existing results (idempotent)
    existing: dict[str, AgentResult] = {}
    if OUTPUT_FILE.exists():
        for raw in json.loads(OUTPUT_FILE.read_text()):
            r = AgentResult(**raw)
            existing[r.repo] = r
        resumable = sum(1 for r in existing.values() if r.n_rollouts < n_rollouts)
        print(f"[S5] Resuming — {len(existing)} repos processed "
              f"({resumable} need more rollouts to reach {n_rollouts})")

    results: dict[str, AgentResult] = dict(existing)
    results_lock = threading.Lock()

    todo = [t for t in targets
            if not (results.get(t.repo) and results[t.repo].n_rollouts >= n_rollouts)]

    def _process_one(target: AgentTarget) -> AgentResult:
        with results_lock:
            prev = results.get(target.repo)
        already = prev.n_rollouts if prev else 0
        print(f"\n  {target.repo} (expected {target.expected_pass} tests)"
              f"{f' [resuming from rollout {already}]' if already else ''}")
        result = _process_target(target, baseline_map, n_rollouts,
                                 dry_run=dry_run, existing_result=prev, model=model,
                                 early_stop=early_stop, max_steps=max_steps)

        if not dry_run:
            print(f"  [{target.repo}] → pass_rate={result.pass_rate} "
                  f"difficulty={result.difficulty} "
                  f"successes={result.n_success}/{result.n_rollouts}")

        with results_lock:
            results[target.repo] = result
            OUTPUT_FILE.write_text(
                json.dumps([r.model_dump() for r in results.values()], indent=2, default=str)
            )
        return result

    effective_workers = min(workers, len(todo)) if todo else 1
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = {pool.submit(_process_one, t): t for t in todo}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                t = futures[future]
                print(f"  [ERROR] {t.repo}: {exc}")

    solved = [r for r in results.values() if r.n_success > 0]
    print(f"\n[S5] Done. {len(solved)}/{len(results)} repos with ≥1 success → {OUTPUT_FILE}")
    return list(results.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="S5: Agent-based multi-rollout solve")
    parser.add_argument("--n-rollouts", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true",
                        help="Build images only; skip agent calls")
    parser.add_argument("--repo", default=None,
                        help="Run only for a specific repo (owner/name)")
    _MODELS = [
        "claude-sonnet-4.6", "claude-sonnet-4.5", "claude-haiku-4.5",
        "claude-opus-4.6", "claude-opus-4.6-fast", "claude-opus-4.5",
        "claude-sonnet-4", "gemini-3-pro-preview",
        "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2",
        "gpt-5.1-codex-max", "gpt-5.1-codex", "gpt-5.1", "gpt-5.1-codex-mini",
        "gpt-5-mini", "gpt-4.1",
    ]
    parser.add_argument("--start", type=int, default=0,
                        help="Start index into agent_targets.json (inclusive, default: 0)")
    parser.add_argument("--end", type=int, default=None,
                        help="End index into agent_targets.json (exclusive, default: all)")
    parser.add_argument("--max-repos", type=int, default=None,
                        help="Maximum number of repos to process (default: all)")
    parser.add_argument("--early-stop", action="store_true",
                        help="Stop rollouts for a repo as soon as one succeeds")
    parser.add_argument("--max-steps", type=int, default=_MAX_STEPS_DEFAULT,
                        help=f"Max agent tool-call steps per rollout before terminating "
                             f"(default: {_MAX_STEPS_DEFAULT})")
    parser.add_argument("--workers", type=int, default=4,
                        help="Number of repos to process in parallel (default: 4)")
    parser.add_argument("--model", default="claude-sonnet-4.6", choices=_MODELS,
                        metavar="MODEL",
                        help=f"Copilot model to use. Choices: {', '.join(_MODELS)}. "
                             "Defaults to whatever is set in ~/.copilot/config.json")
    args = parser.parse_args()
    run(n_rollouts=args.n_rollouts, dry_run=args.dry_run,
        repo_filter=args.repo, model=args.model, workers=args.workers,
        early_stop=args.early_stop, max_steps=args.max_steps,
        max_repos=args.max_repos, start_index=args.start, end_index=args.end)


if __name__ == "__main__":
    main()

