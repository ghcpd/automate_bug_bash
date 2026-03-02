"""Emit Harbor task directories from verified, scored repo metadata."""
from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path

from .models import ScoredRepo
from .strategies.base import LanguageStrategy


def _get_uv_version() -> str:
    """Return the installed uv version string (e.g. '0.8.22'), or empty string."""
    try:
        result = subprocess.run(
            ["uv", "--version"], capture_output=True, text=True, timeout=10
        )
        # output: "uv 0.8.22"
        parts = result.stdout.strip().split()
        return parts[1] if len(parts) >= 2 else ""
    except Exception:
        return ""

_INSTRUCTION_TEMPLATE = """\
# Dev Environment Setup: {owner}/{repo}

You have been given the source code for `{owner}/{repo}` (commit `{short_sha}`)
at `/app`. The repository has been cloned but no dependencies have been installed.

Your task is to set up the development environment so that the project's
test suite runs successfully.

**Constraints:**
- Do **not** modify any test files.
- Do **not** mock or stub out dependencies.
- The test runner is `{test_runner}`.
- All required packages must be installable from PyPI (no private registries).
"""

_TASK_TOML_TEMPLATE = """\
version = "1.0"

[metadata]
author_name = "tb-pipeline"
difficulty = "{difficulty}"
category = "dev-environment-setup"
tags = ["setup", "{language}", "pytest"]

[verifier]
timeout_sec = 300.0

[agent]
timeout_sec = 1800.0

[environment]
build_timeout_sec = 600.0
cpus = 2
memory_mb = 4096
storage_mb = 20480
"""

_DOCKERFILE_TEMPLATE = """\
{base}
# Clone repo at pinned commit — agent starts from here
RUN git clone https://github.com/{owner}/{repo}.git /app && \\
    cd /app && (git checkout {sha} --quiet 2>/dev/null || \\
    (git fetch --depth=1 origin {sha} && git checkout {sha} --quiet))

WORKDIR /app
"""

_SOLVE_SH_TEMPLATE = """\
#!/bin/bash
# Reference solution: install dev dependencies using the verified strategy
set -euo pipefail
cd /app
{setup_cmd}
"""

_SOLVE_SH_FROZEN_TEMPLATE = """\
#!/bin/bash
# Reference solution: install from pinned requirements snapshot
set -euo pipefail
cd /app
uv venv /opt/venv --quiet
uv pip install --python /opt/venv/bin/python -r /solution/requirements-frozen.txt --quiet
"""

# Patterns for lines that set up the Python virtualenv / install Python packages.
# These are replaced with the frozen install when frozen_requirements is available.
_PYTHON_SETUP_RES = [
    re.compile(r"^\s*uv\s+venv\s"),
    re.compile(r"^\s*uv\s+pip\s+install\s"),
    re.compile(r"^\s*uv\s+sync\b"),
    re.compile(r"^\s*pip[0-9.]?\s+install\s"),
    re.compile(r"^\s*pip[0-9.]?\s+install\b"),
    re.compile(r"^\s*python[0-9.]?\s+-m\s+pip\s+install\s"),
    re.compile(r"^\s*python[0-9.]?\s+-m\s+venv\s"),
    re.compile(r"^\s*virtualenv\s"),
    re.compile(r"^\s*source\s+\S*activate\b"),
    re.compile(r"^\s*\.\s+\S*activate\b"),
    re.compile(r"^\s*export\s+PATH=.*venv"),
]

_FROZEN_INSTALL_LINES = [
    "uv venv /opt/venv --quiet",
    "uv pip install --python /opt/venv/bin/python -r /solution/requirements-frozen.txt --quiet",
]


def _augment_with_frozen(solve_content: str) -> str:
    """Return solve_content with Python env setup replaced by frozen install.

    System package commands (apt-get, etc.) and all other lines are preserved
    verbatim.  The two frozen-install lines replace the first block of Python
    env-setup lines encountered; if none are found they are appended at the end.
    Handles multiline commands joined with backslash continuation.
    """
    lines = solve_content.splitlines()
    out: list[str] = []
    frozen_inserted = False
    skip_continuation = False  # True while dropping backslash-continued lines
    for line in lines:
        if skip_continuation:
            # Still inside a dropped multiline command
            if not line.rstrip().endswith("\\"):
                skip_continuation = False
            continue
        if any(p.match(line) for p in _PYTHON_SETUP_RES):
            if not frozen_inserted:
                out.extend(_FROZEN_INSTALL_LINES)
                frozen_inserted = True
            # If this line continues onto next lines, drop those too
            if line.rstrip().endswith("\\"):
                skip_continuation = True
        else:
            out.append(line)
    if not frozen_inserted:
        out.extend(_FROZEN_INSTALL_LINES)
    return "\n".join(out).rstrip() + "\n"

_TEST_SH_TEMPLATE = """\
#!/bin/bash
# Verifier: run pytest and compute ratio-based reward
set -uo pipefail

mkdir -p /logs/verifier
cd /app

# Anti-tampering: reject if test files were modified
if git diff HEAD -- '*/test_*.py' '*_test.py' | grep -q '^+'; then
  echo 0 > /logs/verifier/reward.txt
  echo '{"score": 0.0, "reason": "test_files_modified"}' > /logs/verifier/reward.json
  exit 0
fi

# Use whichever python the solve.sh setup created
if [ -x /app/.venv/bin/python ]; then PYTHON=/app/.venv/bin/python
else PYTHON=/opt/venv/bin/python; fi

# Run pytest with JUnit XML output for reliable parsing
EXTRA=""
$PYTHON -c "import pytest_benchmark" 2>/dev/null && EXTRA="$EXTRA --benchmark-skip"
$PYTHON -c "import pytest_timeout"   2>/dev/null && EXTRA="$EXTRA --timeout=120"
$PYTHON -m pytest --tb=no -q --continue-on-collection-errors \\
  --junit-xml=/tmp/pytest_results.xml $EXTRA 2>&1 | tail -1

BASELINE=$($PYTHON -c "import json; print(json.load(open('/tests/baseline.json'))['expected_pass'])")

# Parse results from JUnit XML — more reliable than stdout scraping
PASS=$($PYTHON -c "
import xml.etree.ElementTree as ET, sys
try:
    root = ET.parse('/tmp/pytest_results.xml').getroot()
    suite = root if root.tag == 'testsuite' else root.find('testsuite')
    t = int(suite.attrib.get('tests', 0))
    f = int(suite.attrib.get('failures', 0))
    e = int(suite.attrib.get('errors', 0))
    s = int(suite.attrib.get('skipped', 0))
    print(max(0, t - f - e - s))
except Exception:
    print(0)
" 2>/dev/null || echo 0)

SCORE=$($PYTHON -c "print(round(min(1.0, int('$PASS') / max(1, $BASELINE)), 4))")

printf '%s\\n' "$SCORE" > /logs/verifier/reward.txt
printf '{"score": %s, "passed": %s, "baseline": %s}\\n' "$SCORE" "$PASS" "$BASELINE" \\
  > /logs/verifier/reward.json
"""

class TaskWriter:
    """Write a Harbor task directory for a verified, scored repo."""

    def __init__(self, tasks_root: Path, strategy: LanguageStrategy) -> None:
        self.tasks_root = tasks_root
        self.strategy = strategy
        self._uv_version = _get_uv_version()  # captured once at init

    def write(self, repo: ScoredRepo, expected_pass: int) -> Path:
        """Write all task files and return the task directory path."""
        owner, name = repo.repo.split("/", 1)
        short_sha = repo.sha[:7]
        task_name = self.strategy.task_name(owner, name, short_sha)
        task_dir = self.tasks_root / task_name

        (task_dir / "environment").mkdir(parents=True, exist_ok=True)
        (task_dir / "solution").mkdir(parents=True, exist_ok=True)
        (task_dir / "tests").mkdir(parents=True, exist_ok=True)

        self._write_instruction(task_dir, owner, name, short_sha)
        self._write_task_toml(task_dir, repo.difficulty)
        self._write_dockerfile(task_dir, owner, name, repo.sha)
        # Write frozen requirements snapshot if available (agent-solved repos only)
        if repo.frozen_requirements:
            self._write_frozen_requirements(task_dir, repo.frozen_requirements)
        # Use frozen requirements in solve.sh when available; fall back to live install
        self._write_solve_sh(
            task_dir,
            solve_content=repo.solve_sh or repo.setup_strategy or "",
            frozen_requirements=repo.frozen_requirements,
        )
        self._write_test_sh(task_dir)
        # Agent repos: use oracle_pass_count (what the best solve actually achieved)
        # Trivial repos: fall back to CI expected_pass
        baseline = repo.oracle_pass_count if repo.oracle_pass_count > 0 else expected_pass
        self._write_baseline(task_dir, repo.sha, baseline)

        return task_dir

    # ------------------------------------------------------------------

    def _write_instruction(self, task_dir: Path, owner: str, repo: str,
                           short_sha: str) -> None:
        text = _INSTRUCTION_TEMPLATE.format(
            owner=owner, repo=repo, short_sha=short_sha,
            test_runner=self.strategy.test_runner(),
        )
        (task_dir / "instruction.md").write_text(text)

    def _write_task_toml(self, task_dir: Path, difficulty: str) -> None:
        text = _TASK_TOML_TEMPLATE.format(
            difficulty=difficulty, language=self.strategy.language,
        )
        (task_dir / "task.toml").write_text(text)

    def _write_dockerfile(self, task_dir: Path, owner: str, repo: str,
                          sha: str) -> None:
        base = self.strategy.dockerfile_base().rstrip()
        if self._uv_version:
            # Replace the latest-uv installer with a versioned URL — no pip needed
            base = base.replace(
                "RUN curl -LsSf https://astral.sh/uv/install.sh | sh",
                f"RUN curl -LsSf https://astral.sh/uv/{self._uv_version}/install.sh | sh",
            )
        text = _DOCKERFILE_TEMPLATE.format(base=base, owner=owner, repo=repo, sha=sha)
        (task_dir / "environment" / "Dockerfile").write_text(text)

    def _write_frozen_requirements(self, task_dir: Path, frozen: str) -> None:
        path = task_dir / "solution" / "requirements-frozen.txt"
        path.write_text(frozen)

    def _write_solve_sh(self, task_dir: Path, solve_content: str,
                        frozen_requirements: str = "") -> None:
        if frozen_requirements:
            if solve_content.startswith("#!") or "set -" in solve_content[:60]:
                # Augment original script: keep system deps, replace Python setup
                text = _augment_with_frozen(solve_content)
            else:
                text = _SOLVE_SH_FROZEN_TEMPLATE
        elif solve_content.startswith("#!") or "set -" in solve_content[:60]:
            # Already a complete script — use as-is
            text = solve_content
        else:
            text = _SOLVE_SH_TEMPLATE.format(setup_cmd=solve_content)
        path = task_dir / "solution" / "solve.sh"
        path.write_text(text)
        path.chmod(0o755)

    def _write_test_sh(self, task_dir: Path) -> None:
        path = task_dir / "tests" / "test.sh"
        path.write_text(_TEST_SH_TEMPLATE)
        path.chmod(0o755)

    def _write_baseline(self, task_dir: Path, sha: str,
                        expected_pass: int) -> None:
        baseline = {"sha": sha, "expected_pass": expected_pass}
        (task_dir / "tests" / "baseline.json").write_text(
            json.dumps(baseline, indent=2)
        )
