"""Pydantic models for each intermediate pipeline schema."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Candidate(BaseModel):
    """Output of S1: a repo that passed pre-filter checks."""

    repo: str  # "owner/name"
    sha: str   # pinned commit from repo list
    default_branch: str = "main"
    stars: int = 0
    size_kb: int
    dep_file: str  # which dependency file was found first
    has_tests: bool
    last_pushed: str = ""  # ISO date string
    prescan_count: int = 0  # estimated test count from static analysis


class CIJobResult(BaseModel):
    """Pytest counts from a single pytest run inside a single CI job."""

    job_id: int
    job_name: str
    passed: int
    failed: int = 0
    errors: int = 0
    skipped: int = 0


class CIBaseline(BaseModel):
    """Output of S2: CI baseline extracted from a successful Actions run."""

    repo: str
    sha: str
    workflow_run_id: int
    job_id: int                # id of the job with the highest individual pass count
    expected_pass: int         # max(job.passed) across all job_results; used by S3/S4
    expected_fail: int = 0
    expected_error: int = 0
    ci_duration_sec: Optional[int] = None
    parsed_at: datetime = Field(default_factory=datetime.utcnow)
    job_results: list[CIJobResult] = Field(default_factory=list)
    # ^ one entry per distinct pytest run across all CI jobs; used by S5 oracle matching


class VerifiedRepo(BaseModel):
    """Output of S3 triage: rule-based setup attempt + infeasibility classification."""

    repo: str
    sha: str
    tag: str = "needs_agent"   # "trivial_success" | "needs_agent" | "infeasible"
    setup_strategy: str        # winning install command (empty if tag != trivial_success)
    setup_time_sec: float
    scores: list[float]        # one per stability run (empty if setup never succeeded)
    mean_score: float
    accepted: bool             # True only for trivial_success with score >= threshold
    rejection_reason: Optional[str] = None
    # Failure logs per strategy — populated for needs_agent/infeasible repos
    failure_logs: dict[str, str] = Field(default_factory=dict)


class AgentTarget(BaseModel):
    """Output of S4: a needs_agent repo cleared for agent-based solving."""

    repo: str
    sha: str
    dep_file: str
    expected_pass: int         # from CI baseline
    failure_logs: dict[str, str]  # from S3 triage
    infeasible_reason: Optional[str] = None  # populated if pre-filter would reject


class AgentRollout(BaseModel):
    """Result of a single agent rollout attempt for one repo."""

    repo: str
    sha: str
    rollout_id: int
    score: float
    success: bool
    passed_count: int = 0      # raw test count from JUnit XML verification
    total_count: int = 0       # total tests collected (passed + failed + errors + skipped)
    failures_count: int = 0    # number of test failures
    errors_count: int = 0      # number of collection/runtime errors
    trajectory_path: str       # path to the exported JSONL trajectory
    solve_sh: str = ""         # populated on success
    frozen_requirements: str = ""  # pip freeze output captured after successful install
    failure_reason: Optional[str] = None
    model: str = ""            # copilot model used for this rollout


class AgentResult(BaseModel):
    """Aggregated result across all rollouts for one repo."""

    repo: str
    sha: str
    n_rollouts: int
    n_success: int
    pass_rate: float
    difficulty: str            # "easy" | "medium" | "hard" | "very_hard"
    best_solve_sh: str = ""    # from the highest-scoring successful rollout
    frozen_requirements: str = ""  # pip freeze from the best successful rollout
    oracle_pass_count: int = 0  # max passed count from any successful rollout; used as scoring denominator
    rollouts: list[AgentRollout] = Field(default_factory=list)


class DifficultyBreakdown(BaseModel):
    setup_steps: int
    build_required: bool
    setup_time_sec: float
    error_diversity: int
    test_count: int
    composite_score: float


class ScoredRepo(BaseModel):
    """Output of S6 difficulty scoring: a verified repo with difficulty label."""

    repo: str
    sha: str
    source: str = "trivial"    # "trivial" (rule-based success) | "agent" (S5 solved)
    setup_strategy: str = ""   # winning install command; empty for agent-solved repos
    setup_time_sec: float = 0.0
    mean_score: float = 0.0
    difficulty: str = "medium" # "easy" | "medium" | "hard" | "very_hard"
    solve_sh: str = ""         # best solve script (from S5 for agent repos, from strategy for trivial)
    frozen_requirements: str = ""  # pip freeze snapshot from the winning S5 rollout
    oracle_pass_count: int = 0 # from S5: max passed count across successful rollouts; 0 for trivial repos
    score_breakdown: Optional[DifficultyBreakdown] = None


class OracleResult(BaseModel):
    """Result of a single oracle run for a task."""

    task_dir: str
    score: float
    run_index: int
    stdout: str = ""
    stderr: str = ""


class AcceptedTask(BaseModel):
    """Output of S6: a task that passed oracle sweep acceptance."""

    task_dir: str
    repo: str
    sha: str
    difficulty: str
    oracle_scores: list[float]
    mean_score: float
    accepted: bool
    rejection_reason: Optional[str] = None
