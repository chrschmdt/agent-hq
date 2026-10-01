from __future__ import annotations

import httpx
from pydantic import SecretStr

from ahq.domain import ConfigurationError, EvalRun

API = "https://api.github.com"
WORKFLOW = "eval.yml"


class GitHubWorkflows:
    def __init__(self, token: SecretStr, repo: str, ref: str, *, workflow: str = WORKFLOW, base_url: str = API) -> None:
        self._token = token
        self._repo = repo
        self._ref = ref
        self._url = f"{base_url}/repos/{repo}/actions/workflows/{workflow}/dispatches"

    async def launch(self, run: EvalRun) -> None:
        headers = {
            "Authorization": f"Bearer {self._token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = {"ref": self._ref, "inputs": {"eval_run_id": run.eval_run_id}}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(self._url, headers=headers, json=body)
        if response.status_code not in (httpx.codes.OK, httpx.codes.NO_CONTENT):
            raise ConfigurationError(f"GitHub did not start the eval workflow for {self._repo}: {response.status_code}")
