# Copilot Instructions for tb-pipeline

## Project Overview

**tb-pipeline** transforms GitHub repositories into Harbor dev-env evaluation tasks. The primary user-facing tool is `scripts/test_single_repo.py`, which tests a single repo end-to-end in Docker and produces reproducible artifacts (Dockerfile, setup/test commands). A background 8-step batch pipeline (S1–S8) processes repos at scale.

---

## `scripts/test_single_repo.py` — Primary Script

### What It Does

Tests a single GitHub Python repo at a specific commit inside Docker. It:
1. **Builds a Docker image** with the repo cloned at the target SHA
2. **Tries rule-based setup strategies** (ordered `uv` install commands) — runs setup + pytest together; only `passed > 0` counts as success
3. **Optionally falls back to Copilot CLI agent** if rule-based strategies all fail
4. **Generates artifacts**: Dockerfile, setup_cmd.sh, run_test.sh, solve.sh, metadata.json

### CLI Reference

```
python3.11 scripts/test_single_repo.py [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo OWNER/NAME` | *(required)* | GitHub repo in `owner/name` format |
| `--sha SHA` | latest on default branch | Commit SHA or branch to checkout |
| `--dep-file FILE` | auto (try all) | Primary dependency file: `pyproject.toml`, `setup.cfg`, `setup.py`, `requirements.txt` |
| `--strategy CMD` | auto (try all) | Force a specific setup command string |
| `--timeout SECS` | 1200 | Container timeout in seconds |
| `--keep-image` | false | Keep the Docker image after testing |
| `--use-agent` | false | Fall back to Copilot CLI agent if rule-based fails |
| `--agent-only` | false | Skip rule-based; go straight to Copilot agent |
| `--model NAME` | *(copilot default)* | Copilot model (e.g. `claude-sonnet-4.6`, `gpt-5.1`) |
| `--max-steps N` | 50 | Max agent tool-call steps before terminating |

### Usage Examples

```bash
# Basic: auto-detect everything
python3.11 scripts/test_single_repo.py --repo pallets/flask

# Specific commit
python3.11 scripts/test_single_repo.py --repo pallets/flask --sha 6047e0db

# With AI agent fallback
python3.11 scripts/test_single_repo.py --repo psf/requests --use-agent

# Agent-only with model selection
python3.11 scripts/test_single_repo.py --repo owner/repo --agent-only --model claude-sonnet-4.6

# Force a specific dep file
python3.11 scripts/test_single_repo.py --repo owner/repo --dep-file requirements.txt
```

### Workflow: 3-Step Process

#### Step 1 — Build Docker Image
- Uses `PythonStrategy.dockerfile_base()` (Ubuntu 24.04 + Python 3 + `uv`)
- Clones repo, checks out target SHA (shallow fetch fallback for full SHAs)
- Image tagged as `test-{owner}-{name}-{sha[:7]}`

#### Step 2 — Rule-Based Strategy Search
When `--dep-file` and `--strategy` are NOT specified, the script:
1. Iterates all dep files from `PythonStrategy.dep_files()`: `pyproject.toml`, `setup.cfg`, `setup.py`, `requirements.txt`
2. For each dep file, gets ordered strategies from `PythonStrategy.setup_strategies(dep_file)`
3. Deduplicates across dep files (same command won't run twice)
4. For each strategy: runs **setup + pytest together** in one container — only considers it a win if `passed > 0`

Strategy order for `pyproject.toml`:
1. `uv sync --all-groups --quiet`
2. `uv sync --dev --quiet`
3. `uv pip install --python /opt/venv/bin/python -e ".[dev,test]" --quiet`
4. `uv pip install --python /opt/venv/bin/python -e ".[test]" --quiet`
5. `uv pip install --python /opt/venv/bin/python -e ".[dev]" --quiet`
6. `uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python pytest`

For `requirements.txt`, additional `pip install -r` strategies are prepended.

**Important**: Unlike naive exit-code checking, the script validates that pytest actually finds passing tests. A strategy that installs successfully but produces 0 passed tests is treated as a failure.

#### Step 2b — Copilot Agent Fallback (optional)
Triggered when: all rule-based strategies fail AND `--use-agent` or `--agent-only` is set.

1. Creates a long-lived Docker container from the built image
2. Builds a structured prompt (`_build_agent_prompt()`) including prior failure logs
3. Invokes `copilot --allow-all -p <prompt>` (optionally with `--model`)
4. Agent drives setup via `docker exec <container> bash -c "..."` commands
5. Agent must write 3 files to `/tmp/`: `_solve.sh`, `_setup_cmd.txt`, `_test_cmd.txt`
6. Script reads those files, then runs JUnit XML-based verification inside the container
7. Step counting: lines matching `^[●•] ` are counted; exceeding `--max-steps` terminates the agent

#### Step 3 — Full Pytest Run & Artifact Generation
- For rule-based wins: re-runs with `--tb=short -q` for detailed output
- For agent wins: uses already-verified results
- Generates a complete self-contained Dockerfile with setup + test baked in
- Saves all artifacts to `output/<owner>__<name>__<sha>/`

### Output Artifacts

Saved to `output/<owner>__<name>__<sha>/`:

| File | Contents |
|------|----------|
| `Dockerfile` | Self-contained: clone + setup + `CMD pytest`. Can `docker build && docker run` directly. |
| `setup_cmd.sh` | Bash script with the install command chain |
| `run_test.sh` | Bash script with the pytest command |
| `solve.sh` | Full solve script (from agent trajectory or generated from winning strategy) |
| `metadata.json` | `{"repo", "sha", "setup_cmd", "test_cmd"}` |

### Key Internal Functions

| Function | Purpose |
|----------|---------|
| `_resolve_default_branch(owner, name)` | Uses `git ls-remote --symref` to find default branch + latest SHA |
| `_build_agent_prompt(...)` | Constructs the Copilot CLI prompt with container name, repo info, and prior failure logs |
| `_run_copilot(cmd, max_steps, wall_timeout)` | Streams Copilot output, counts steps, enforces limits |
| `_run_agent_fallback(...)` | Full agent lifecycle: create container → run copilot → read output files → verify with JUnit |
| `_verify_in_container(container, python_exe)` | Runs pytest with `--junit-xml`, parses XML for precise pass/fail/error counts |
| `_generate_dockerfile(repo, sha, setup_cmd, test_cmd)` | Produces complete standalone Dockerfile |
| `_save_artifacts(...)` | Writes all output files to the output directory |

### Docker Permission Note

On systems where the current user is in the `docker` group but the shell session hasn't refreshed, use:
```bash
sg docker -c "python3.11 scripts/test_single_repo.py --repo owner/name"
```

---

## Docker & Environment Conventions

- **Base image**: Ubuntu 24.04 + Python 3 + `uv` package manager
- **Two virtualenv locations**:
  - `/app/.venv` — created by `uv sync` (PEP 735 dependency-groups)
  - `/opt/venv` — created by `uv venv /opt/venv` + `uv pip install`
- `python_exe()` returns `/app/.venv/bin/python` for `uv sync` strategies, `/opt/venv/bin/python` otherwise
- Always strip `required-version` from `pyproject.toml` before `uv` commands to avoid version mismatch errors

## Pipeline Library Modules Used by the Script

| Module | What test_single_repo.py uses |
|--------|-------------------------------|
| `pipeline.docker_runner.DockerRunner` | `build_image()`, `run_commands()`, `remove_image()` — ephemeral Docker container lifecycle |
| `pipeline.strategies.get_strategy("python")` | Returns `PythonStrategy` — provides `dockerfile_base()`, `dep_files()`, `setup_strategies()`, `python_exe()`, `parse_test_output()` |
| `pipeline.strategies.python.PythonStrategy` | Strategy pattern implementation: ordered install commands, pytest output parsing, dep file detection |

## Background: 8-Step Batch Pipeline (S1–S8)

The batch pipeline processes repos at scale. Each step reads prior JSON from `data/` and writes its own:

| Step | Module | Purpose |
|------|--------|---------|
| S1 | `s1_search` | Pre-filter repos with pytest from JSONL input |
| S2 | `s2_ci_baseline` | Extract CI test counts from GitHub Actions logs |
| S3 | `s3_local_verify` | Docker-based rule setup + pytest verify (same strategy logic as test_single_repo.py) |
| S4 | `s4_prefilter` | Classify repos as actionable/infeasible |
| S5 | `s5_agent_solve` | Copilot CLI multi-rollout agent solving (agent logic adapted into test_single_repo.py) |
| S6 | `s6_difficulty` | Assign difficulty labels based on agent pass rates |
| S7 | `s7_task_gen` | Generate Harbor task directories |
| S8 | `s8_oracle_sweep` | Oracle verification sweep |

Run any step: `python -m pipeline.steps.s1_search`

## Code Conventions

- Python ≥ 3.11; uses `from __future__ import annotations`
- Pydantic v2 `BaseModel` for inter-step data models
- Ruff linting, line length 100
- Type hints on all function signatures
- Docker-isolated: all setup/test execution in ephemeral containers

## Environment Setup

```bash
pip install -e ".[dev]"
export GITHUB_TOKEN=<your-token>   # Required for GitHub API calls

# Test a single repo (primary workflow)
python3.11 scripts/test_single_repo.py --repo owner/name --use-agent

# Run batch pipeline steps
python -m pipeline.steps.s1_search
```

## Adding a New Language

1. Create `pipeline/strategies/<lang>.py` subclassing `LanguageStrategy`
2. Implement: `dep_files()`, `setup_strategies()`, `parse_test_output()`, `dockerfile_base()`, `python_exe()`
3. Register in `pipeline/strategies/__init__.py`
