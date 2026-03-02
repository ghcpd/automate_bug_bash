#!/usr/bin/env python3
"""Test a single GitHub repo at a specific commit in Docker.

Clones the repo, checks out the given SHA, tries setup strategies in order,
and runs pytest — mirroring what S3 does but for a single user-specified repo.

When all rule-based strategies fail and --use-agent is set, falls back to
Copilot CLI to let an AI agent figure out the correct setup command.

Usage:
    python -m scripts.test_single_repo --repo owner/name --sha abc1234
    python -m scripts.test_single_repo --repo owner/name --sha abc1234 --use-agent
    python -m scripts.test_single_repo --repo owner/name --sha abc1234 --agent-only
    python -m scripts.test_single_repo --repo owner/name --sha abc1234 --dep-file requirements.txt
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

# Ensure the project root is on sys.path so we can import pipeline.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.docker_runner import DockerRunner
from pipeline.strategies import get_strategy

# Output directory for generated artifacts
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def _safe_tag(repo: str, sha: str) -> str:
    owner, name = repo.split("/", 1)
    safe_owner = owner.lower().replace("_", "-")
    safe_name = name.lower().replace("_", "-")
    return f"tb-test/{safe_owner}-{safe_name}-{sha[:7]}"


def _container_name(repo: str, sha: str) -> str:
    safe = repo.replace("/", "-").replace("_", "-").lower()
    return f"tb-single-{safe}-{sha[:7]}"


def _resolve_default_branch(owner: str, name: str) -> tuple[str, str]:
    """Use git ls-remote to find the default branch and its HEAD SHA.

    Returns (sha, branch_name).
    """
    result = subprocess.run(
        ["git", "ls-remote", "--symref", f"https://github.com/{owner}/{name}.git", "HEAD"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to query default branch for {owner}/{name}: {result.stderr.strip()}"
        )

    # Parse output like:
    #   ref: refs/heads/main	HEAD
    #   abc123...	HEAD
    branch = "main"
    sha = ""
    for line in result.stdout.splitlines():
        if line.startswith("ref:"):
            # e.g. "ref: refs/heads/main\tHEAD"
            ref_part = line.split()[1]
            branch = ref_part.replace("refs/heads/", "")
        else:
            parts = line.split()
            if parts and len(parts[0]) >= 7:
                sha = parts[0]

    if not sha:
        raise RuntimeError(f"Could not resolve HEAD for {owner}/{name}")
    return sha, branch


def _output_dir_for_repo(repo: str, sha: str) -> Path:
    """Create and return an output directory for this repo's artifacts."""
    owner, name = repo.split("/", 1)
    d = OUTPUT_DIR / f"{owner}__{name}__{sha[:7]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _generate_dockerfile(repo: str, sha: str, setup_cmd: str, test_cmd: str) -> str:
    """Generate a complete, self-contained Dockerfile."""
    owner, name = repo.split("/", 1)
    strategy = get_strategy("python")
    base = strategy.dockerfile_base()

    return (
        f"{base}"
        f"# Clone repo and checkout specific commit\n"
        f"RUN git clone https://github.com/{owner}/{name}.git /app && \\\n"
        f"    cd /app && (git checkout {sha} --quiet 2>/dev/null || \\\n"
        f"    (git fetch --depth=1 origin {sha} && git checkout {sha} --quiet))\n"
        f"WORKDIR /app\n"
        f"\n"
        f"# Install dependencies\n"
        f"RUN {setup_cmd}\n"
        f"\n"
        f"# Default command: run tests\n"
        f'CMD ["bash", "-c", "{test_cmd}"]\n'
    )


def _save_artifacts(repo: str, sha: str, setup_cmd: str, test_cmd: str,
                    dockerfile: str, solve_sh: str = "") -> Path:
    """Save all generated artifacts to the output directory."""
    out = _output_dir_for_repo(repo, sha)

    # 1. Dockerfile
    (out / "Dockerfile").write_text(dockerfile)

    # 2. setup_cmd.sh
    setup_script = f"#!/bin/bash\nset -e\ncd /app\n{setup_cmd}\n"
    (out / "setup_cmd.sh").write_text(setup_script)

    # 3. run_test.sh
    test_script = f"#!/bin/bash\nset -e\ncd /app\n{test_cmd}\n"
    (out / "run_test.sh").write_text(test_script)

    # 4. solve.sh (if available)
    if solve_sh:
        (out / "solve.sh").write_text(solve_sh)

    # 5. metadata
    meta = {
        "repo": repo,
        "sha": sha,
        "setup_cmd": setup_cmd,
        "test_cmd": test_cmd,
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))

    return out


# ── Copilot agent helpers (adapted from S5) ─────────────────────────

_STEP_RE = re.compile(r"^[●•] ")


def _build_agent_prompt(repo: str, dep_file: str, container_name: str,
                        failure_logs: dict[str, str]) -> str:
    """Build the copilot -p prompt for agent-based setup."""
    owner, name = repo.split("/", 1)

    prior_attempts = ""
    if failure_logs:
        lines = []
        for cmd, log in list(failure_logs.items())[:3]:
            short_cmd = cmd[:80]
            last_err = [l for l in log.splitlines() if l.strip()][-3:]
            lines.append(f"  Command tried: {short_cmd}")
            lines.append("  Last output:\n" + "\n".join(f"    {l}" for l in last_err))
        prior_attempts = "Prior rule-based attempts (all failed):\n" + "\n".join(lines)

    return textwrap.dedent(f"""\
        You are a developer setting up a Python project's dev environment inside a Docker container.

        Container name: {container_name}
        Repo: {owner}/{name}
        Dependency file: {dep_file}

        The repo is already cloned at /app inside the container.
        No dependencies have been installed yet.

        {prior_attempts}

        Your goal: install all dependencies so that `python -m pytest --tb=no -q` passes
        with at least some tests passing.

        Rules:
        - Use `docker exec {container_name} bash -c "..."` for ALL commands inside the container.
        - Do NOT modify any test files (files matching test_*.py or *_test.py).
        - The container has `uv` available. Prefer uv over pip.
        - If a venv is needed, use `/opt/venv` (uv venv /opt/venv) unless uv sync creates .venv.

        When you have confirmed that pytest passes, you MUST write THREE files on the HOST:

        1. /tmp/{container_name}_solve.sh — complete bash script with all install commands
           (self-contained, reproducible from a fresh clone; NO pytest in this file)

        2. /tmp/{container_name}_setup_cmd.txt — a SINGLE LINE containing the exact shell
           command chain that installs all dependencies.
           Example: uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[dev,test]" --quiet

        3. /tmp/{container_name}_test_cmd.txt — a SINGLE LINE containing the exact shell
           command to run the tests.
           Example: /opt/venv/bin/python -m pytest --tb=short -q

        Start by inspecting the repo structure and dependency file, then install.
    """).strip()


def _run_copilot(cmd: list[str], max_steps: int,
                 wall_timeout: int) -> tuple[int, str, str]:
    """Run copilot subprocess, streaming stdout line-by-line.

    Returns (returncode, trajectory_text, failure_reason_or_empty).
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, bufsize=1,
    )

    lines: list[str] = []
    step_count = 0
    terminated_reason = ""

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
            # Print agent output in real-time
            print(f"        {line}", end="")
            if _STEP_RE.match(line):
                step_count += 1
                if step_count >= max_steps:
                    terminated_reason = f"max_steps({max_steps})"
                    proc.terminate()
                    for tail in proc.stdout:
                        lines.append(tail)
                    break
    finally:
        proc.stdout.close()
        proc.wait()

    trajectory = "".join(lines)
    rc = proc.returncode if not terminated_reason else -1
    return rc, trajectory, terminated_reason


def _extract_solve_sh_from_trajectory(trajectory: str, container_name: str) -> str:
    """Extract docker exec commands from copilot output and build a solve.sh."""
    pattern = rf'docker exec {re.escape(container_name)} bash -c "([^"]+)"'
    cmds = re.findall(pattern, trajectory)
    pattern_sq = rf"docker exec {re.escape(container_name)} bash -c '([^']+)'"
    cmds += re.findall(pattern_sq, trajectory)
    if not cmds:
        return ""
    lines = ["#!/bin/bash", "# Auto-extracted from copilot trajectory",
             "set -e", "cd /app", ""] + cmds
    return "\n".join(lines) + "\n"


def _verify_in_container(container_name: str) -> dict[str, int]:
    """Run pytest inside the container and parse output for test counts."""
    import xml.etree.ElementTree as ET

    xml_path_in = "/tmp/pytest_results.xml"
    xml_path_host = Path(f"/tmp/{container_name}_junit.xml")
    empty = {"passed": 0, "failed": 0, "error": 0, "total": 0}

    # Try both venv locations
    cmd = textwrap.dedent(f"""\
        cd /app
        if [ -x /app/.venv/bin/python ]; then PY=/app/.venv/bin/python
        elif [ -x /opt/venv/bin/python ]; then PY=/opt/venv/bin/python
        else PY=python3; fi
        $PY -m pytest --tb=no -q --continue-on-collection-errors \\
            --junit-xml={xml_path_in} 2>&1
    """)

    try:
        subprocess.run(
            ["docker", "exec", container_name, "bash", "-c", cmd],
            capture_output=True, text=True, timeout=600,
        )
        cp = subprocess.run(
            ["docker", "cp", f"{container_name}:{xml_path_in}", str(xml_path_host)],
            capture_output=True,
        )
        if cp.returncode != 0 or not xml_path_host.exists():
            return empty

        tree = ET.parse(xml_path_host)
        root = tree.getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is None:
            return empty
        total = int(suite.attrib.get("tests", 0))
        failures = int(suite.attrib.get("failures", 0))
        errors = int(suite.attrib.get("errors", 0))
        skipped = int(suite.attrib.get("skipped", 0))
        passed = max(0, total - failures - errors - skipped)
        return {"passed": passed, "failed": failures, "error": errors, "total": total}

    except (subprocess.TimeoutExpired, ET.ParseError, Exception):
        return empty
    finally:
        xml_path_host.unlink(missing_ok=True)


def _run_agent_fallback(repo: str, sha: str, dep_file: str, image_tag: str,
                        failure_logs: dict[str, str], timeout: int,
                        model: str, max_steps: int) -> dict | None:
    """Use Copilot CLI to let AI figure out setup. Returns result dict or None."""
    if not shutil.which("copilot"):
        print("\n      ERROR: 'copilot' CLI not found in PATH.")
        print("      Install it: https://docs.github.com/en/copilot/copilot-cli")
        return None

    cname = _container_name(repo, sha)
    solve_sh_host = Path(f"/tmp/{cname}_solve.sh")

    # Remove leftover container
    subprocess.run(["docker", "rm", "-f", cname], capture_output=True)

    # Start a long-running container from image
    print(f"      Starting container: {cname}")
    result = subprocess.run(
        ["docker", "run", "-d", "--name", cname, image_tag,
         "sleep", str(timeout + 120)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"      ERROR: Failed to start container: {result.stderr}")
        return None

    setup_cmd_host = Path(f"/tmp/{cname}_setup_cmd.txt")
    test_cmd_host = Path(f"/tmp/{cname}_test_cmd.txt")

    try:
        prompt = _build_agent_prompt(repo, dep_file, cname, failure_logs)
        cmd = ["copilot", "--allow-all", "-p", prompt]
        if model:
            cmd += ["--model", model]

        print(f"      Launching copilot agent{' (model=' + model + ')' if model else ''} …\n")
        returncode, trajectory, term_reason = _run_copilot(cmd, max_steps, timeout)

        if term_reason:
            print(f"\n      Agent terminated: {term_reason}")

        # Read agent outputs
        solve_sh = ""
        if solve_sh_host.exists():
            solve_sh = solve_sh_host.read_text()
            solve_sh_host.unlink(missing_ok=True)

        setup_cmd = ""
        if setup_cmd_host.exists():
            setup_cmd = setup_cmd_host.read_text().strip()
            setup_cmd_host.unlink(missing_ok=True)

        test_cmd = ""
        if test_cmd_host.exists():
            test_cmd = test_cmd_host.read_text().strip()
            test_cmd_host.unlink(missing_ok=True)

        # Verify
        print("\n      Verifying agent result …")
        verify = _verify_in_container(cname)

        if not solve_sh and verify["passed"] > 0:
            solve_sh = _extract_solve_sh_from_trajectory(trajectory, cname)

        # Infer setup_cmd / test_cmd from solve.sh or trajectory if agent didn't write them
        if not setup_cmd and solve_sh:
            # Use solve.sh content (minus shebang/comments/set-e/cd) as setup_cmd
            cmd_lines = [l for l in solve_sh.splitlines()
                         if l.strip() and not l.startswith("#")
                         and not l.strip().startswith("set ")
                         and l.strip() != "cd /app"]
            setup_cmd = " && ".join(cmd_lines)
        if not test_cmd:
            # Default test command based on venv detection
            if "uv sync" in (setup_cmd or "") or ".venv" in (setup_cmd or ""):
                test_cmd = "/app/.venv/bin/python -m pytest --tb=short -q"
            else:
                test_cmd = "/opt/venv/bin/python -m pytest --tb=short -q"

        return {
            "counts": verify,
            "solve_sh": solve_sh,
            "setup_cmd": setup_cmd,
            "test_cmd": test_cmd,
            "trajectory": trajectory,
        }

    except Exception as exc:
        print(f"      Agent error: {exc}")
        return None
    finally:
        # Stop and remove container
        try:
            subprocess.run(["docker", "stop", "--time=5", cname],
                           capture_output=True, timeout=15)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", cname], capture_output=True)
        try:
            subprocess.run(["docker", "rm", "-f", cname],
                           capture_output=True, timeout=30)
        except Exception:
            pass


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test a single GitHub repo at a specific commit in Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s --repo pallets/flask
              %(prog)s --repo pallets/flask --sha 6047e0db
              %(prog)s --repo psf/requests --use-agent
              %(prog)s --repo owner/repo --agent-only --model claude-sonnet-4.6
        """),
    )
    parser.add_argument("--repo", required=True,
                        help="GitHub repo in owner/name format")
    parser.add_argument("--sha", default=None,
                        help="Commit SHA or branch (default: latest commit on default branch)")
    parser.add_argument("--dep-file", default=None,
                        choices=["pyproject.toml", "setup.cfg", "setup.py", "requirements.txt"],
                        help="Primary dependency file (default: auto-detect, try all)")
    parser.add_argument("--timeout", type=int, default=1200,
                        help="Container timeout in seconds (default: 1200)")
    parser.add_argument("--keep-image", action="store_true",
                        help="Do not remove the Docker image after testing")
    parser.add_argument("--strategy", type=str, default=None,
                        help="Force a specific setup command instead of trying all strategies")

    # Agent options
    agent_group = parser.add_argument_group("AI agent options")
    agent_group.add_argument("--use-agent", action="store_true",
                             help="Fall back to Copilot CLI agent if rule-based strategies fail")
    agent_group.add_argument("--agent-only", action="store_true",
                             help="Skip rule-based strategies; go straight to Copilot agent")
    agent_group.add_argument("--model", default="",
                             help="Copilot model to use (e.g. claude-sonnet-4.6, gpt-5.1)")
    agent_group.add_argument("--max-steps", type=int, default=50,
                             help="Max agent tool-call steps before terminating (default: 50)")
    args = parser.parse_args()

    if "/" not in args.repo:
        parser.error("--repo must be in owner/name format, e.g. pallets/flask")

    if args.agent_only:
        args.use_agent = True

    repo = args.repo
    dep_file = args.dep_file  # None means "try all"
    timeout = args.timeout
    owner, name = repo.split("/", 1)

    # Resolve SHA: if not specified, use latest commit on default branch
    sha = args.sha
    if sha is None:
        sha, branch = _resolve_default_branch(owner, name)
        print(f"  Resolved default branch: {branch} → {sha[:12]}")

    strategy = get_strategy("python")
    runner = DockerRunner()
    image_tag = _safe_tag(repo, sha)

    # ── Step 1: Build Docker image ──────────────────────────────────
    total_steps = 3 if not args.agent_only else 2
    step = 0

    print(f"\n{'='*60}")
    print(f"  Repo:       {repo}")
    print(f"  SHA:        {sha}")
    print(f"  Dep file:   {dep_file or 'auto (try all)'}")
    print(f"  Timeout:    {timeout}s")
    print(f"  Agent:      {'agent-only' if args.agent_only else 'fallback' if args.use_agent else 'disabled'}")
    if args.model:
        print(f"  Model:      {args.model}")
    print(f"{'='*60}\n")

    step += 1
    print(f"[{step}/{total_steps}] Building Docker image …")
    dockerfile = (
        strategy.dockerfile_base()
        + f"RUN git clone https://github.com/{owner}/{name}.git /app && "
        f"cd /app && (git checkout {sha} --quiet 2>/dev/null || "
        f"(git fetch --depth=1 origin {sha} && git checkout {sha} --quiet))\n"
        "WORKDIR /app\n"
    )
    try:
        runner.build_image(dockerfile, image_tag, timeout=600)
        print(f"      Image built: {image_tag}")
    except Exception as exc:
        print(f"      ERROR: Docker build failed:\n{exc}")
        sys.exit(1)

    # ── Step 2: Rule-based strategies ───────────────────────────────
    winning_cmd = None
    winning_counts = None
    failure_logs: dict[str, str] = {}

    if not args.agent_only:
        step += 1
        print(f"\n[{step}/{total_steps}] Finding working setup strategy (rule-based) …")
        print("      (each strategy runs setup + pytest together in one container)\n")

        if args.strategy:
            strategies_with_dep = [(dep_file or "pyproject.toml", args.strategy)]
        elif dep_file:
            # Single dep file → its strategies
            strategies_with_dep = [(dep_file, s) for s in strategy.setup_strategies(dep_file)]
        else:
            # No dep file specified → try all dep files × their strategies (deduplicated)
            seen: set[str] = set()
            strategies_with_dep = []
            for df in strategy.dep_files():
                for s in strategy.setup_strategies(df):
                    if s not in seen:
                        seen.add(s)
                        strategies_with_dep.append((df, s))

        total_strategies = len(strategies_with_dep)
        for i, (cur_dep_file, setup_cmd) in enumerate(strategies_with_dep, 1):
            label = setup_cmd if len(setup_cmd) <= 80 else setup_cmd[:77] + "…"
            dep_tag = f" [{cur_dep_file}]" if not dep_file else ""
            print(f"      Strategy {i}/{total_strategies}{dep_tag}: {label}")

            python_exe = strategy.python_exe(setup_cmd)
            quick_test_cmd = f"{python_exe} -m pytest --tb=no -q 2>&1"

            try:
                result = runner.run_commands(
                    image_tag,
                    [setup_cmd, quick_test_cmd],
                    timeout=timeout,
                    network_disabled=False,
                )
            except TimeoutError:
                print(f"        ✗ Timed out")
                failure_logs[setup_cmd] = "timeout"
                continue
            except Exception as exc:
                print(f"        ✗ Error: {exc}")
                failure_logs[setup_cmd] = str(exc)
                continue

            counts = strategy.parse_test_output(result["stdout"])
            if counts["passed"] > 0:
                print(f"        ✓ Passed! ({counts['passed']} passed, "
                      f"{counts['failed']} failed, {counts['error']} errors, "
                      f"{result['elapsed_sec']:.1f}s)")
                winning_cmd = setup_cmd
                winning_counts = counts
                break
            else:
                tail = "\n".join(result["stdout"].splitlines()[-10:])
                print(f"        ✗ No passing tests (exit code {result['exit_code']})")
                if tail.strip():
                    for line in tail.splitlines():
                        print(f"          {line}")
                failure_logs[setup_cmd] = tail

        if winning_cmd is None:
            print("\n      All rule-based strategies failed.")
            if not args.use_agent:
                if failure_logs:
                    print("\n      Failure summary:")
                    for cmd, log in failure_logs.items():
                        short_cmd = cmd if len(cmd) <= 60 else cmd[:57] + "…"
                        print(f"        - {short_cmd}")
                        first_line = log.strip().splitlines()[0] if log.strip() else "(empty)"
                        print(f"          → {first_line}")
                print("\n      Tip: re-run with --use-agent to let Copilot AI try.")
                if not args.keep_image:
                    runner.remove_image(image_tag, force=True)
                sys.exit(1)

    # ── Step 2b / Agent fallback ────────────────────────────────────
    agent_result = None
    if winning_cmd is None and args.use_agent:
        step += 1
        label = "agent-only" if args.agent_only else "AI agent fallback"
        print(f"\n[{step}/{total_steps}] {label} — using Copilot CLI …")
        agent_result = _run_agent_fallback(
            repo, sha, dep_file or "pyproject.toml", image_tag, failure_logs,
            timeout, args.model, args.max_steps,
        )
        if agent_result and agent_result["counts"]["passed"] > 0:
            winning_counts = agent_result["counts"]
            winning_cmd = agent_result.get("setup_cmd", "(agent-generated)")
            print(f"\n      ✓ Agent succeeded! "
                  f"({winning_counts['passed']} passed, "
                  f"{winning_counts['failed']} failed, "
                  f"{winning_counts['error']} errors)")
        else:
            print(f"\n      ✗ Agent failed to produce passing tests.")
            if not args.keep_image:
                runner.remove_image(image_tag, force=True)
            sys.exit(1)

    if winning_cmd is None:
        if not args.keep_image:
            runner.remove_image(image_tag, force=True)
        sys.exit(1)

    # ── Step 3: Full test run with detailed output ──────────────────
    # Only re-run for rule-based wins (agent already verified in-place)
    if agent_result is None:
        step += 1
        print(f"\n[{step}/{total_steps}] Running full pytest with detailed output …")
        python_exe = strategy.python_exe(winning_cmd)
        test_cmd = f"{python_exe} -m pytest --tb=short -q 2>&1"
        print(f"      Strategy:  {winning_cmd}")
        print(f"      Test cmd:  {test_cmd}")

        try:
            result = runner.run_commands(
                image_tag,
                [winning_cmd, test_cmd],
                timeout=timeout,
                network_disabled=False,
            )
        except TimeoutError:
            print(f"      ✗ Test run timed out after {timeout}s")
            if not args.keep_image:
                runner.remove_image(image_tag, force=True)
            sys.exit(1)

        counts = strategy.parse_test_output(result["stdout"])
        exit_code = result["exit_code"]
        elapsed = result["elapsed_sec"]

        output_lines = result["stdout"].splitlines()
        display_lines = output_lines[-50:] if len(output_lines) > 50 else output_lines
        print(f"\n{'─'*60}")
        for line in display_lines:
            print(f"  {line}")
        print(f"{'─'*60}")
    else:
        counts = winning_counts
        exit_code = 0 if counts["passed"] > 0 else 1
        elapsed = 0.0

    # ── Determine setup_cmd and test_cmd ─────────────────────────────
    if agent_result:
        setup_cmd = agent_result.get("setup_cmd", winning_cmd)
        test_cmd = agent_result.get("test_cmd", "")
        solve_sh = agent_result.get("solve_sh", "")
    else:
        setup_cmd = winning_cmd
        python_exe = strategy.python_exe(winning_cmd)
        test_cmd = f"{python_exe} -m pytest --tb=short -q"
        solve_sh = f"#!/bin/bash\nset -e\ncd /app\n{winning_cmd}\n"

    # ── Generate Dockerfile ─────────────────────────────────────────
    dockerfile_content = _generate_dockerfile(repo, sha, setup_cmd, test_cmd)

    # ── Save all artifacts ──────────────────────────────────────────
    out_dir = _save_artifacts(repo, sha, setup_cmd, test_cmd,
                              dockerfile_content, solve_sh)

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Passed:    {counts['passed']}")
    print(f"  Failed:    {counts['failed']}")
    print(f"  Errors:    {counts['error']}")
    if agent_result is None:
        print(f"  Exit code: {exit_code}")
        print(f"  Elapsed:   {elapsed:.1f}s")

    print(f"\n  ── Setup Command ──")
    print(f"  {setup_cmd}")
    print(f"\n  ── Test Command ──")
    print(f"  {test_cmd}")

    print(f"\n  ── Dockerfile ──")
    for line in dockerfile_content.splitlines():
        print(f"  {line}")

    print(f"\n  ── Artifacts saved to ──")
    print(f"  {out_dir}/")
    for f in sorted(out_dir.iterdir()):
        print(f"    {f.name}")

    print(f"{'='*60}")
    print(f"\n  Quick start:")
    owner, name = repo.split("/", 1)
    safe_tag = f"{owner.lower()}-{name.lower()}-{sha[:7]}"
    print(f"    docker build -t {safe_tag} {out_dir}")
    print(f"    docker run --rm {safe_tag}")
    print()

    # Cleanup
    if not args.keep_image:
        runner.remove_image(image_tag, force=True)
        print(f"  Image removed: {image_tag}")
    else:
        print(f"  Image kept: {image_tag}")

    sys.exit(0 if counts["passed"] > 0 else 1)


if __name__ == "__main__":
    main()
