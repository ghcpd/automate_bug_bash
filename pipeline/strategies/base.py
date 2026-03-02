"""Abstract base class for language-specific pipeline strategies."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class LanguageStrategy(ABC):
    """Encapsulates all language-specific logic for the pipeline.

    To add a new language (e.g. Go, JavaScript):
    1. Create a new file in strategies/ (e.g. go.py)
    2. Subclass LanguageStrategy and implement all abstract methods
    3. Register it in strategies/__init__.py
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Canonical language name used in search queries and metadata."""

    @property
    @abstractmethod
    def github_search_qualifier(self) -> str:
        """GitHub search language qualifier, e.g. 'language:Python'."""

    @abstractmethod
    def dep_files(self) -> list[str]:
        """Ordered list of dependency filenames to look for in repo root."""

    @abstractmethod
    def test_runner(self) -> str:
        """Test runner executable, e.g. 'pytest'."""

    @abstractmethod
    def has_test_marker(self, dep_file_content: str) -> bool:
        """Return True if the test runner is listed as a dependency."""

    @abstractmethod
    def setup_strategies(self, dep_file: str) -> list[str]:
        """Ordered list of shell commands to try for environment setup.

        Each command should install all dev/test dependencies.
        Strategies are attempted in order; the first that exits 0 wins.
        """

    @abstractmethod
    def run_tests_command(self) -> str:
        """Shell command to run the test suite and emit a parseable summary."""

    @abstractmethod
    def parse_test_output(self, output: str) -> dict[str, int]:
        """Parse test runner output and return {'passed': N, 'failed': M, 'error': K}."""

    def dockerfile_base(self) -> str:
        """Dockerfile FROM line and base apt packages for this language."""
        return (
            "FROM ubuntu:24.04\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            "git curl ca-certificates build-essential && "
            "rm -rf /var/lib/apt/lists/*\n"
        )

    def task_name(self, owner: str, repo: str, short_sha: str) -> str:
        """Canonical task directory name (lowercase for Docker image name compatibility)."""
        return f"{owner.lower()}__{repo.lower()}__{short_sha}"
