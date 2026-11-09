"""The proposal log: every action an agent proposed or took, with its rung, its evidence and what a person did with it.

``POST /agent-proposals`` (``cases:write``, the permission agents already use to raise approvals) records one; a proposal with no evidence is refused (see app.services.agent_proposals).
``GET /agent-proposals`` (``alerts:read``) lists them newest first with the header counts. ``POST /agent-proposals/{id}/outcome`` records what a person made of it and needs a signed-in person's session
(an agent's token cannot mark its own proposal). Nothing here approves, resolves or grants anything.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, require_permission, require_signed_in_session
from app.db.rls import TenantDBSession
from app.models.agent_proposal import AgentProposal
from app.models.responder import AgentApproval
from app.services.agent_proposals import EvidenceError, clean_evidence, tally
from app.services.audit import emit_audit

router = APIRouter(prefix="/agent-proposals", tags=["autonomy"])

MAX_LIST = 200


class ProposalIn(BaseModel):
    agent: str = Field(min_length=1, max_length=120)
    action_type: str = Field(min_length=1, max_length=80)
    target: str = Field(default="", max_length=300)
    summary: str = Field(min_length=1, max_length=4000)
    rung: Literal["shadow", "suggest", "ask", "act_tell", "act_quiet"]
    evidence: list[Any] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    approval_id: uuid.UUID | None = None


class OutcomeIn(BaseModel):
    outcome: Literal["accepted", "edited", "rejected", "expired"]
    note: str | None = Field(default=None, max_length=2000)


class ProposalOut(BaseModel):
    id: uuid.UUID
    agent: str
    action_type: str
    target: str
    summary: str
    rung: str
    evidence: list[dict[str, Any]]
    confidence: float | None
    approval_id: uuid.UUID | None
    outcome: str
    outcome_note: str | None
    outcome_at: datetime | None
    created_at: datetime


class ProposalList(BaseModel):
    items: list[ProposalOut]
    summary: dict[str, Any]


def _out(r: AgentProposal) -> ProposalOut:
    return ProposalOut(
        id=r.id, agent=r.agent, action_type=r.action_type, target=r.target, summary=r.summary, rung=r.rung, evidence=list(r.evidence or []), confidence=r.confidence,
        approval_id=r.approval_id, outcome=r.outcome, outcome_note=r.outcome_note, outcome_at=r.outcome_at, created_at=r.created_at,
    )


@router.get("", response_model=ProposalList, dependencies=[Depends(require_permission("alerts:read"))])
async def list_proposals(
    user: AuthUser,
    db: TenantDBSession,
    agent: str | None = Query(default=None, max_length=120),
    rung: str | None = Query(default=None, pattern="^(shadow|suggest|ask|act_tell|act_quiet)$"),
    limit: int = Query(default=100, ge=1, le=MAX_LIST),
) -> ProposalList:
    where = [AgentProposal.tenant_id == user.tenant_id]
    if agent:
        where.append(AgentProposal.agent == agent)
    if rung:
        where.append(AgentProposal.rung == rung)
    rows = (await db.execute(select(AgentProposal).where(*where).order_by(AgentProposal.created_at.desc()).limit(limit))).scalars().all()
    return ProposalList(items=[_out(r) for r in rows], summary=tally([{"rung": r.rung, "outcome": r.outcome} for r in rows]))


@router.post("", response_model=ProposalOut, status_code=status.HTTP_201_CREATED)
async def record_proposal(body: ProposalIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("cases:write"))], db: TenantDBSession) -> ProposalOut:
    try:
        evidence = clean_evidence(body.evidence)
    except EvidenceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if body.approval_id is not None:
        card = await db.get(AgentApproval, body.approval_id)
        if card is None or card.tenant_id != user.tenant_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="approval_id is not one of your tenant's approvals")
    row = AgentProposal(
        tenant_id=user.tenant_id, agent=body.agent.strip(), action_type=body.action_type.strip().lower(), target=body.target.strip(), summary=body.summary.strip(), rung=body.rung,
        evidence=evidence, confidence=body.confidence, approval_id=body.approval_id,
    )
    db.add(row)
    await db.flush()
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="agent_proposal:recorded", resource="agent_proposal", resource_id=str(row.id), changes={"agent": row.agent, "rung": row.rung, "action_type": row.action_type}, request=request)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.post("/{proposal_id}/outcome", response_model=ProposalOut, dependencies=[Depends(require_signed_in_session)])
async def set_outcome(proposal_id: uuid.UUID, body: OutcomeIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("cases:write"))], db: TenantDBSession) -> ProposalOut:
    row = (await db.execute(select(AgentProposal).where(AgentProposal.id == proposal_id, AgentProposal.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    if row.outcome != "none":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Already marked {row.outcome}.")
    row.outcome, row.outcome_note, row.outcome_by, row.outcome_at = body.outcome, (body.note or None), user.user_id, datetime.now(UTC)
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="agent_proposal:outcome", resource="agent_proposal", resource_id=str(row.id), changes={"outcome": body.outcome}, request=request)
    await db.commit()
    await db.refresh(row)
    return _out(row)
