from __future__ import annotations

from fastapi import APIRouter

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import Approval, ApprovalDecision, ApprovalId

router = APIRouter(tags=["approvals"])


@router.get("/api/approvals")
async def pending_approvals(container: ContainerDep) -> list[Approval]:
    return await container.approvals.pending()


@router.get("/api/approvals/{approval_id}")
async def get_approval(approval_id: ApprovalId, container: ContainerDep) -> Approval:
    return await container.approvals.get(approval_id)


@router.post("/api/approvals/{approval_id}/decision")
async def decide(
    approval_id: ApprovalId, decision: ApprovalDecision, container: ContainerDep, operator: Operator
) -> Approval:
    return await container.commands.decide_approval(approval_id, decision, actor=operator)
