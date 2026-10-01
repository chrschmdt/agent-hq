from __future__ import annotations

import secrets
from typing import NewType

WorkItemId = NewType("WorkItemId", str)
ApprovalId = NewType("ApprovalId", str)
RunId = NewType("RunId", str)
ThreadId = NewType("ThreadId", str)
JobId = NewType("JobId", str)


def _new(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def new_work_item_id() -> WorkItemId:
    return WorkItemId(_new("wi"))


def new_approval_id() -> ApprovalId:
    return ApprovalId(_new("apv"))


def new_run_id() -> RunId:
    return RunId(_new("run"))


def new_sim_run_id() -> str:
    return _new("sim")


def new_ticket_id() -> str:
    return _new("tk")


def new_job_id() -> JobId:
    return JobId(_new("job"))


def thread_for(work_item_id: WorkItemId) -> ThreadId:
    return ThreadId(f"th_{work_item_id}")
