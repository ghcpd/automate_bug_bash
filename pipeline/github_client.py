"""Rate-limited GitHub REST API client with response caching."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

GITHUB_API = "https://api.github.com"
_CACHE_DIR = Path(__file__).parent.parent / "data" / ".cache"


class GitHubClient:
    """Thin wrapper around the GitHub REST API.

    - Injects Authorization header from GITHUB_TOKEN env var
    - Caches GET responses to disk so re-runs don't re-fetch
    - Exponential backoff on 429 / 5xx responses
    - Raises clearly if GITHUB_TOKEN is missing
    """

    def __init__(self, cache: bool = True) -> None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN environment variable is not set. "
                "Export a GitHub personal access token before running the pipeline."
            )
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self._cache = cache
        if cache:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def search_repos(self, query: str, per_page: int = 30, max_results: int = 2000
                     ) -> list[dict]:
        """Paginate GitHub repo search and return raw repo dicts."""
        results: list[dict] = []
        page = 1
        while len(results) < max_results:
            params = {"q": query, "per_page": per_page, "page": page}
            data = self.get("/search/repositories", params=params)
            items = data.get("items", [])
            if not items:
                break
            results.extend(items)
            page += 1
            if len(items) < per_page:
                break  # last page
            time.sleep(0.5)  # stay within search rate limit
        return results[:max_results]

    def get_contents(self, owner: str, repo: str, path: str,
                     ref: Optional[str] = None) -> dict:
        """Fetch a single file's metadata (includes download_url / content)."""
        endpoint = f"/repos/{owner}/{repo}/contents/{path}"
        params = {"ref": ref} if ref else {}
        return self.get(endpoint, params=params)

    def get_file_text(self, owner: str, repo: str, path: str,
                      ref: Optional[str] = None) -> str:
        """Return the decoded text content of a file."""
        import base64
        data = self.get_contents(owner, repo, path, ref=ref)
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        # Fall back to download_url
        url = data.get("download_url")
        if url:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        raise ValueError(f"Cannot decode file {path} in {owner}/{repo}")

    def list_workflow_runs(self, owner: str, repo: str, status: str = "success",
                           per_page: int = 5) -> list[dict]:
        endpoint = f"/repos/{owner}/{repo}/actions/runs"
        params = {"status": status, "per_page": per_page}
        data = self.get(endpoint, params=params)
        return data.get("workflow_runs", [])

    def list_jobs(self, owner: str, repo: str, run_id: int) -> list[dict]:
        endpoint = f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
        data = self.get(endpoint)
        return data.get("jobs", [])

    def get_job_logs(self, owner: str, repo: str, job_id: int) -> str:
        """Download raw log text for a job (follows redirect)."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs"
        cache_key = self._cache_path(url, {})
        if self._cache and cache_key.exists():
            return cache_key.read_text(encoding="utf-8")
        resp = self._session.get(url, timeout=60, allow_redirects=True)
        resp.raise_for_status()
        text = resp.text
        if self._cache:
            cache_key.write_text(text, encoding="utf-8")
        return text

    def get_default_branch_sha(self, owner: str, repo: str,
                               branch: str = "HEAD") -> str:
        """Return the SHA of the tip of the default branch."""
        data = self.get(f"/repos/{owner}/{repo}/commits/{branch}")
        return data["sha"]

    # ------------------------------------------------------------------
    # Core GET with caching + retry
    # ------------------------------------------------------------------

    @retry(stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=1, min=2, max=60),
           reraise=True)
    def get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        url = f"{GITHUB_API}{endpoint}"
        cache_key = self._cache_path(url, params or {})
        if self._cache and cache_key.exists():
            return json.loads(cache_key.read_text())

        resp = self._session.get(url, params=params, timeout=30)

        # Respect secondary rate limit
        if resp.status_code == 429 or (resp.status_code == 403
                                        and "rate limit" in resp.text.lower()):
            retry_after = int(resp.headers.get("Retry-After", "60"))
            print(f"  [rate-limit] sleeping {retry_after}s …")
            time.sleep(retry_after)
            resp = self._session.get(url, params=params, timeout=30)

        # Don't retry client errors (4xx) — they won't resolve on retry
        if 400 <= resp.status_code < 500:
            resp.raise_for_status()

        resp.raise_for_status()
        data = resp.json()
        if self._cache:
            cache_key.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _cache_path(self, url: str, params: dict) -> Path:
        key = url + json.dumps(params, sort_keys=True)
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        return _CACHE_DIR / h
