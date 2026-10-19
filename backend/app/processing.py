import logging
import time
from datetime import timedelta
from uuid import uuid4

from pydantic import Field, ValidationError
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, Retry
from rq.job import Job
from rq.serializers import JSONSerializer
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.agent import execute_agent
from app.application import Problem, event, fingerprint, inquiry, require
from app.config import settings
from app.domain import Input
from app.infrastructure import engine
from app.intake import extract_document
from app.llm import ProviderError, provider
from app.models import AgentCall, ProcessingRun, QuoteVersion, as_utc, now

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "needs_clarification", "manual_review"}


class ProcessInput(Input):
    clarification: str = Field(default="", max_length=20000)


def connection(worker=False):
    return Redis.from_url(
        settings().redis_url, socket_connect_timeout=3, socket_timeout=None if worker else 5
    )


def create_run(db, identifier, data, key, actor):
    item = inquiry(db, identifier, lock=True)
    digest = fingerprint({"inquiry_id": identifier, **data.model_dump(mode="json")})
    previous = db.scalar(select(ProcessingRun).where(ProcessingRun.operation_key == key))
    if previous:
        if previous.fingerprint != digest:
            raise Problem(409, "Ключ обработки использован с другими данными")
        return previous
    if item.confirmed_revision:
        raise Problem(409, "Подтверждённое КП нельзя обрабатывать заново")
    busy = db.scalar(
        select(ProcessingRun).where(
            ProcessingRun.inquiry_id == identifier, ProcessingRun.status.in_(["queued", "running"])
        )
    )
    if busy:
        raise Problem(
            409, "У заявки уже есть активная обработка; дождитесь её или повторите тот же ключ"
        )
    config = settings()
    run = ProcessingRun(
        id=str(uuid4()),
        inquiry_id=identifier,
        operation_key=key,
        fingerprint=digest,
        clarification=data.clarification,
        base_revision=item.revision,
        provider=config.llm_provider,
        model="deterministic-mock" if config.llm_provider == "mock" else config.llm_model,
        status="queued",
        attempt=0,
    )
    db.add(run)
    event(
        db,
        item,
        actor,
        "processing.queued",
        {"run_id": run.id, "provider": run.provider, "clarification": data.clarification},
    )
    db.commit()
    return run


def dispatch(db, run):
    if run.status in TERMINAL:
        return
    if run.status == "running" and run.lease_until and as_utc(run.lease_until) > now():
        return
    try:
        redis = connection()
        job_id = f"{run.id}-{run.attempt}"
        if Job.exists(job_id, connection=redis):
            job = Job.fetch(job_id, connection=redis, serializer=JSONSerializer)
            if job.get_status(refresh=True) in {"queued", "started", "scheduled", "deferred"}:
                return
        run.status, run.error = "queued", None
        db.commit()
        Queue("proposals", connection=redis, serializer=JSONSerializer).enqueue(
            "app.processing.process_run",
            run.id,
            job_id=job_id,
            job_timeout=settings().agent_timeout + 120,
            result_ttl=86400,
            failure_ttl=604800,
            retry=Retry(max=2),
            description=f"Process proposal {run.id}",
        )
    except RedisError:
        raise Problem(
            503, "Очередь недоступна. Заявка и задача сохранены; повторите с тем же ключом"
        ) from None


def run_view(db, run):
    calls = db.scalars(
        select(AgentCall).where(AgentCall.run_id == run.id).order_by(AgentCall.id)
    ).all()
    return {
        "id": run.id,
        "status": run.status,
        "provider": run.provider,
        "model": run.model,
        "retryable": run.status in {"failed", "queued"}
        or (run.status == "running" and bool(run.lease_until) and as_utc(run.lease_until) <= now()),
        "attempt": run.attempt,
        "error": run.error,
        "result": run.result,
        "extraction": run.extraction,
        "calls": [
            {
                "kind": c.kind,
                "name": c.name,
                "arguments": c.arguments,
                "output": c.output,
                "error": c.error,
                "duration_ms": c.duration_ms,
                "usage": c.usage,
                "attempt": c.attempt,
            }
            for c in calls
        ],
    }


def perform(db, run_id, selected_provider=None):
    config = settings()
    claim = str(uuid4())
    changed = db.execute(
        update(ProcessingRun)
        .where(
            ProcessingRun.id == run_id,
            or_(
                ProcessingRun.status.in_(["queued", "failed"]),
                (ProcessingRun.status == "running") & (ProcessingRun.lease_until < now()),
            ),
        )
        .values(
            status="running",
            claim_token=claim,
            lease_until=now() + timedelta(seconds=config.agent_timeout + 150),
            attempt=ProcessingRun.attempt + 1,
            error=None,
        )
    )
    db.commit()
    run = require(db, ProcessingRun, run_id)
    db.refresh(run)
    if changed.rowcount != 1:
        return {"status": run.status, "duplicate": True}
    started = time.monotonic()
    try:
        item = inquiry(db, run.inquiry_id)
        event(
            db,
            item,
            f"worker:{run.provider}",
            "processing.started",
            {"run_id": run.id, "attempt": run.attempt},
        )
        db.commit()
        recovered = db.scalar(
            select(QuoteVersion).where(QuoteVersion.operation_key == f"agent-{run.id}")
        )
        if recovered:
            result = {"status": "completed", "revision": recovered.revision, "questions": []}
        else:
            if run.provider != config.llm_provider or (
                run.provider == "compatible" and run.model != config.llm_model
            ):
                raise ProviderError("provider_configuration_changed")
            if item.source_info and item.extracted_text is None:
                extracted = extract_document(item.source_info)
                item.extracted_text = extracted
                event(
                    db,
                    item,
                    "worker",
                    "document.extracted",
                    {"sha256": item.source_info["sha256"], "characters": len(extracted)},
                )
                db.commit()
            text = run.clarification or (
                (item.extracted_text + "\n" + item.text) if item.extracted_text else item.text
            )
            result = execute_agent(db, run, text, selected_provider or provider())
        db.refresh(run, with_for_update=True)
        if run.claim_token != claim:
            db.rollback()
            return {"status": run.status, "duplicate": True}
        run.status, run.result, run.error = result["status"], result, None
        run.lease_until = None
        event(
            db,
            item,
            f"agent:{run.provider}",
            f"processing.{run.status}",
            {
                "run_id": run.id,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "result": result,
            },
        )
        db.commit()
        logger.info("Processing run=%s status=%s attempt=%s", run.id, run.status, run.attempt)
        return result
    except Exception as error:
        db.rollback()
        db.refresh(run)
        if run.claim_token != claim:
            return {"status": run.status, "duplicate": True}
        run.status, run.lease_until = "failed", None
        run.error = (
            error.message
            if isinstance(error, Problem)
            else str(error)
            if isinstance(error, ProviderError)
            else "invalid_provider_schema"
            if isinstance(error, ValidationError)
            else type(error).__name__
        )
        event(
            db,
            inquiry(db, run.inquiry_id),
            "worker",
            "processing.failed",
            {
                "run_id": run.id,
                "error": run.error,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )
        db.commit()
        logger.error("Processing failed run=%s code=%s", run.id, run.error)
        raise ProviderError(run.error) from None


def process_run(run_id):
    with Session(engine(), expire_on_commit=False) as db:
        return perform(db, run_id)
