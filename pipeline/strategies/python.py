"""Language strategy for Python repos using pytest."""
from __future__ import annotations

import re

from .base import LanguageStrategy


class PythonStrategy(LanguageStrategy):
    @property
    def language(self) -> str:
        return "python"

    @property
    def github_search_qualifier(self) -> str:
        return "language:Python"

    def dep_files(self) -> list[str]:
        # Checked in order; first match wins
        return ["pyproject.toml", "setup.cfg", "setup.py", "requirements.txt"]

    def test_runner(self) -> str:
        return "pytest"

    def has_test_marker(self, dep_file_content: str) -> bool:
        return "pytest" in dep_file_content.lower()

    def setup_strategies(self, dep_file: str) -> list[str]:
        """Ordered install attempts using uv + virtualenv.

        uv sync creates .venv in the project dir; uv pip install uses /opt/venv.
        The winning strategy is recorded and replayed in solve.sh.
        First exit-0 strategy wins.

        Three pyproject.toml patterns covered:
          1. [dependency-groups] (PEP 735) → uv sync --all-groups / --dev
          2. [project.optional-dependencies] → uv pip install -e ".[dev,test]"
          3. requirements.txt fallback
        """
        # Strip uv required-version pin before any uv command (prevents
        # "Required uv version X does not match running version Y" errors)
        patch_uv_version = (
            "sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true"
        )
        uv_pip = "uv pip install --python /opt/venv/bin/python"
        create_venv = "uv venv /opt/venv --quiet"

        strategies = [
            # PEP 735 dependency-groups (uv sync creates .venv in project dir)
            f"{patch_uv_version} && uv sync --all-groups --quiet",
            f"{patch_uv_version} && uv sync --dev --quiet",
            # Classic optional-dependencies extras (uses /opt/venv)
            f'{patch_uv_version} && {create_venv} && {uv_pip} -e ".[dev,test]" --quiet',
            f'{patch_uv_version} && {create_venv} && {uv_pip} -e ".[test]" --quiet',
            f'{patch_uv_version} && {create_venv} && {uv_pip} -e ".[dev]" --quiet',
            f'{patch_uv_version} && {create_venv} && {uv_pip} -e . --quiet && {uv_pip} pytest --quiet',
        ]
        if dep_file == "requirements.txt":
            strategies = [
                f'{create_venv} && '
                f'{{ {uv_pip} -r requirements-dev.txt --quiet 2>/dev/null; true; }} && '
                f'{uv_pip} -r requirements.txt --quiet && {uv_pip} pytest --quiet',
                f'{create_venv} && {uv_pip} -r requirements.txt --quiet && '
                f'{uv_pip} pytest --quiet',
            ] + strategies
        elif dep_file in ("setup.cfg", "setup.py"):
            strategies = [
                f'{patch_uv_version} && {create_venv} && {uv_pip} -e ".[dev,test]" --quiet',
                f'{patch_uv_version} && {create_venv} && {uv_pip} -e . --quiet && {uv_pip} pytest --quiet',
            ] + strategies[2:]  # skip uv sync strategies for setup.py repos
        return strategies

    def python_exe(self, setup_strategy: str) -> str:
        """Return the Python executable path for a given setup strategy."""
        if setup_strategy.startswith("uv sync"):
            return "/app/.venv/bin/python"
        return "/opt/venv/bin/python"

    def run_tests_command(self) -> str:
        # NOTE: actual command depends on which strategy won (see python_exe())
        # This default is used before strategy is known
        return "/app/.venv/bin/python -m pytest --tb=no -q 2>&1 || " \
               "/opt/venv/bin/python -m pytest --tb=no -q 2>&1"

    def parse_test_output(self, output: str) -> dict[str, int]:
        """Parse pytest summary line into pass/fail/error counts.

        Handles formats like:
          '5 passed'
          '5 passed, 2 failed'
          '5 passed, 1 warning'
          '5 passed, 2 failed, 1 error'
        """
        result = {"passed": 0, "failed": 0, "error": 0}

        # Look for the last summary line (most reliable)
        for line in reversed(output.splitlines()):
            m_pass = re.search(r"(\d+) passed", line)
            if m_pass:
                result["passed"] = int(m_pass.group(1))
                m_fail = re.search(r"(\d+) failed", line)
                if m_fail:
                    result["failed"] = int(m_fail.group(1))
                m_err = re.search(r"(\d+) error", line)
                if m_err:
                    result["error"] = int(m_err.group(1))
                return result

        return result

    def run_tests_command(self) -> str:
        return "python3 -m pytest --tb=no -q 2>&1"

    def dockerfile_base(self) -> str:
        return (
            "FROM ubuntu:24.04\n"
            "ENV DEBIAN_FRONTEND=noninteractive\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            "python3 python3-venv git curl ca-certificates "
            "build-essential && rm -rf /var/lib/apt/lists/*\n"
            # Install uv — avoids pip/Ubuntu 24.04 externally-managed-env issues
            'RUN curl -LsSf https://astral.sh/uv/install.sh | sh\n'
            "ENV PATH=\"/root/.local/bin:$PATH\"\n"
            "RUN ln -sf /usr/bin/python3 /usr/bin/python\n"
        )
