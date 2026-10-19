from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def as_utc(value: datetime):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))


class LoginSession(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    details: Mapped[str] = mapped_column(Text)
    discount: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    discount_kind: Mapped[str] = mapped_column(String(30), default="contract")
    payment_terms: Mapped[str] = mapped_column(String(200))


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(250))
    unit: Mapped[str] = mapped_column(String(20))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    stock: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    lead_days: Mapped[int] = mapped_column(Integer)
    production_days: Mapped[int] = mapped_column(Integer, default=0)
    delivery_days: Mapped[int] = mapped_column(Integer, default=0)


class Inquiry(Base):
    __tablename__ = "inquiries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    text: Mapped[str] = mapped_column(Text)
    source_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    create_key: Mapped[str] = mapped_column(String(100), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(default=0)
    confirmed_revision: Mapped[int | None] = mapped_column(nullable=True)
    lock_version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": lock_version}


class QuoteVersion(Base):
    __tablename__ = "quote_versions"
    __table_args__ = (UniqueConstraint("inquiry_id", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inquiry_id: Mapped[str] = mapped_column(ForeignKey("inquiries.id"))
    revision: Mapped[int] = mapped_column()
    snapshot: Mapped[dict] = mapped_column(JSON)
    operation_key: Mapped[str] = mapped_column(String(100), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    inquiry_id: Mapped[str] = mapped_column(ForeignKey("inquiries.id"), index=True)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProcessingRun(Base):
    __tablename__ = "processing_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inquiry_id: Mapped[str] = mapped_column(ForeignKey("inquiries.id"), index=True)
    operation_key: Mapped[str] = mapped_column(String(100), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    clarification: Mapped[str] = mapped_column(Text, default="")
    base_revision: Mapped[int] = mapped_column()
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    attempt: Mapped[int] = mapped_column(default=0)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentCall(Base):
    __tablename__ = "agent_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id"), index=True)
    attempt: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(80))
    arguments: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column()
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
