"""Sign-in events collected from an identity provider (migration 091)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class SigninEvent(Base):
    __tablename__ = "signin_events"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "source_id", name="uq_signin_events_source"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    user_principal: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country: Mapped[str | None] = mapped_column(String(16), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    app: Mapped[str | None] = mapped_column(String(160), nullable=True)
    client_app: Mapped[str | None] = mapped_column(String(100), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interactive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mfa: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    risk: Mapped[str | None] = mapped_column(String(20), nullable=True)
    conditional_access: Mapped[str | None] = mapped_column(String(40), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class DirectoryAuditEvent(Base):
    """An identity-related entry of the directory audit log (migration 093)."""

    __tablename__ = "directory_audit_events"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "source_id", name="uq_directory_audit_events_source"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actor: Mapped[str] = mapped_column(String(320), nullable=False)
    actor_is_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actor_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activity: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    service: Mapped[str | None] = mapped_column(String(80), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target: Mapped[str | None] = mapped_column(String(320), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sensitivity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class IdentityMfaUser(Base):
    """One person's multi-factor state from the latest snapshot (migration 093)."""

    __tablename__ = "identity_mfa_users"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    upn: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    user_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    licensed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    per_user: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ca_enforced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    security_defaults: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    methods: Mapped[str | None] = mapped_column(String(400), nullable=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientVcioReview(Base):
    """One client's vCIO Toolbox recommendations (counts and the pending ones that matter most) and risks (migration 095)."""

    __tablename__ = "client_vcio_reviews"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    recommendations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientM365Check(Base):
    """One client's Microsoft 365 baseline checks (a list of {key, status, evidence}), read through CIPP by CORE (migration 097)."""

    __tablename__ = "client_m365_checks"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientCheckHistory(Base):
    """A client's tool check appearing, or changing status (migration 103). The newest row per check says since when it has had its current status."""

    __tablename__ = "client_check_history"
    __table_args__ = (Index("ix_client_check_history_tenant_key", "tenant_id", "key", "observed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    evidence: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientCheckAcceptance(Base):
    """A person accepting a failing check for a client, with a reason and an optional end date (migration 103)."""

    __tablename__ = "client_check_acceptances"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    reason: Mapped[str] = mapped_column(String(400), nullable=False)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The check does not apply to this client at all (migration 107): no end date, left out of the score.
    not_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class CoreTool(Base):
    """One of the owner's tools, as CORE reported it: its name and whether it is connected in CORE (migration 115)."""

    __tablename__ = "core_tools"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class CoreSweepRun(Base):
    """The latest pass of one of CORE's per-client sweeps, as CORE reported it (migration 103)."""

    __tablename__ = "core_sweep_runs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    accounts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waiting: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_error: Mapped[str] = mapped_column(String(300), nullable=False, default="")


class ClientLicenseCount(Base):
    """The latest count of one thing a tool counts for a client: licences bought, machines managed, people covered (migration 104)."""

    __tablename__ = "client_license_counts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    item: Mapped[str] = mapped_column(String(80), primary_key=True)
    unit: Mapped[str] = mapped_column(String(12), nullable=False, default="other")
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    available: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientLicenseHistory(Base):
    """One change to a client's count of something: it appeared, its count moved, or it went (count 0) (migration 104)."""

    __tablename__ = "client_license_history"
    __table_args__ = (Index("ix_client_license_history_tenant_item", "tenant_id", "source", "item", "observed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    item: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(12), nullable=False, default="other")
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class BillingItemMap(Base):
    """Which tool counts an invoice line is checked against, for the account that owns the feed (migration 105)."""

    __tablename__ = "billing_item_map"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    invoice_item: Mapped[str] = mapped_column(String(120), primary_key=True)
    counted: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientVcioProposal(Base):
    """Something AiSOC suggests adding to a client's vCIO Toolbox, and what a person decided about it (migration 096)."""

    __tablename__ = "client_vcio_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="vciotoolbox")
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="recommendation")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="Medium")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="suggested")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vendor_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class IdentitySecureScore(Base):
    """One client's latest Microsoft Secure Score with its trend and what is still missing (migration 094)."""

    __tablename__ = "identity_secure_scores"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    max_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    average_score: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    active_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    licensed_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    improvements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientScoreHistory(Base):
    """A client's check score on one day (migration 106): the last report of the day wins."""

    __tablename__ = "client_score_history"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    met: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partly: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_met: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ClientScoreTarget(Base):
    """The score a client should stay at or above (migration 108), owned by the account that owns the feed."""

    __tablename__ = "client_score_targets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    target: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientCheckOwner(Base):
    """Who is looking after a check for a client, and by when (migration 109)."""

    __tablename__ = "client_check_owners"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner: Mapped[str] = mapped_column(String(80), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientCheckComment(Base):
    """One comment in the thread on a client's check (migration 110)."""

    __tablename__ = "client_check_comments"
    __table_args__ = (Index("ix_client_check_comments_tenant_key", "tenant_id", "key", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class BillingDifferenceNote(Base):
    """Why a difference between billed and counted is accepted for one client's invoice line (migration 111)."""

    __tablename__ = "billing_difference_notes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    invoice_item: Mapped[str] = mapped_column(String(120), primary_key=True)
    note: Mapped[str] = mapped_column(String(400), nullable=False)
    difference: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class CheckWeight(Base):
    """How much a check counts towards every client's score, 1 to 5 (migration 112)."""

    __tablename__ = "check_weights"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    weight: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ClientCheckItemHistory(Base):
    """An item joining or leaving the list behind a client's check (migration 114)."""

    __tablename__ = "client_check_item_history"
    __table_args__ = (Index("ix_client_check_item_history_tenant_key", "tenant_id", "key", "observed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    item: Mapped[str] = mapped_column(String(120), nullable=False)
    event: Mapped[str] = mapped_column(String(8), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
