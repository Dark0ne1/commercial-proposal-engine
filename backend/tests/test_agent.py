import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fakeredis import FakeRedis
from rq import Queue, SimpleWorker
from rq.serializers import JSONSerializer
from rq.timeouts import TimerDeathPenalty
from sqlalchemy import func, select, update

from app.application import create_inquiry
from app.config import settings
from app.domain import InquiryInput
from app.llm import CompatibleProvider, Extraction, MockProvider, ProviderError, Reply, ToolCall
from app.models import AgentCall, Inquiry, ProcessingRun, QuoteVersion, now
from app.processing import ProcessInput, create_run, dispatch, perform, run_view

SCENARIOS = json.loads(Path(__file__).with_name("agent_golden.json").read_text(encoding="utf-8"))


def setup_run(db, text="SKU-0001, 2 шт.", key="agent-test-key"):
    item = create_inquiry(db, InquiryInput(customer_id=1, text=text), f"inquiry-{key}", "manager")
    run = create_run(db, item.id, ProcessInput(), key, "manager")
    return item, run


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_golden_agent(db, scenario):
    item, run = setup_run(db, scenario["text"])
    result = perform(db, run.id, MockProvider())
    assert result["status"] == scenario["status"]
    db.refresh(item)
    assert item.confirmed_revision is None
    if result["status"] == "completed":
        quote = db.scalar(select(QuoteVersion))
        assert quote.snapshot["total"] == scenario["total"]
        calls = db.scalars(select(AgentCall).where(AgentCall.kind == "tool")).all()
        assert {c.name for c in calls} == {
            "get_customer",
            "search_catalog",
            "get_price",
            "check_availability",
            "calculate_quote",
            "create_quote_draft",
        }
        assert all(c.duration_ms >= 0 for c in calls)
    else:
        assert result["questions"]
        assert db.scalar(select(func.count()).select_from(QuoteVersion)) == 0


def test_repeated_and_recovered_run(db):
    item, run = setup_run(db)
    perform(db, run.id, MockProvider())
    assert perform(db, run.id, MockProvider())["duplicate"]
    run.status, run.lease_until = "running", now() - timedelta(seconds=1)
    db.commit()
    assert perform(db, run.id, MockProvider())["revision"] == 1
    assert db.scalar(select(func.count()).select_from(QuoteVersion)) == 1
    assert db.get(Inquiry, item.id).revision == 1


def test_clarification_creates_draft_after_review(db):
    item, run = setup_run(db, "Клапан Ду25, 2 шт.")
    assert perform(db, run.id, MockProvider())["status"] == "manual_review"
    clarified = create_run(
        db, item.id, ProcessInput(clarification="SKU-0001, 2 шт."), "clarified-key", "manager"
    )
    assert perform(db, clarified.id, MockProvider())["status"] == "completed"
    assert len(db.scalars(select(ProcessingRun)).all()) == 2


class Malicious(MockProvider):
    def __init__(self, name, arguments):
        self.name, self.arguments = name, arguments

    def reply(self, messages, tools):
        return Reply(calls=[ToolCall(id="call-1", name=self.name, arguments=self.arguments)])


@pytest.mark.parametrize(
    "name,arguments,error",
    [
        ("execute_sql", {"sql": "DROP TABLE products"}, "unknown_tool"),
        (
            "get_price",
            {"product_id": 1, "line_index": 0, "price": "0.01"},
            "invalid_tool_arguments",
        ),
        ("get_price", {"product_id": 2, "line_index": 0}, "product_not_uniquely_resolved"),
        ("create_quote_draft", {}, "calculation_required"),
        ("search_catalog", {"line_index": 99}, "invalid_line_index"),
    ],
)
def test_tool_boundary(db, name, arguments, error):
    item, run = setup_run(db)
    with pytest.raises((ProviderError,)):
        perform(db, run.id, Malicious(name, arguments))
    assert run.status == "failed"
    assert db.scalar(select(func.count()).select_from(QuoteVersion)) == 0
    assert db.scalars(select(AgentCall).where(AgentCall.kind == "tool")).first().error == error
    assert db.get(Inquiry, item.id).confirmed_revision is None


def test_fabricated_extraction_is_not_a_quote(db):
    class Fabricates(MockProvider):
        def extract(self, text):
            return Extraction(
                lines=[{"query": "SKU-0001", "quantity": "100", "unit": "шт", "source": text}]
            ), None

    item, run = setup_run(db)
    assert perform(db, run.id, Fabricates())["status"] == "needs_clarification"
    assert db.scalar(select(func.count()).select_from(QuoteVersion)) == 0


def test_omitted_sku_cannot_be_silently_dropped(db):
    class Omits(MockProvider):
        def extract(self, text):
            self.extraction = Extraction(
                lines=[
                    {
                        "query": "SKU-0001",
                        "quantity": "2",
                        "unit": "шт",
                        "source": "SKU-0001, 2 шт.",
                    }
                ]
            )
            return self.extraction, None

    item, run = setup_run(db, "SKU-0001, 2 шт.\nSKU-0002, 1 шт.")
    assert perform(db, run.id, Omits())["status"] == "needs_clarification"


def test_agent_wall_clock_timeout(db, monkeypatch):
    clock = {"value": 0}
    monkeypatch.setattr("app.agent.time.monotonic", lambda: clock["value"])

    class Slow(MockProvider):
        def extract(self, text):
            result = super().extract(text)
            clock["value"] += settings().agent_timeout + 1
            return result

    item, run = setup_run(db)
    with pytest.raises(ProviderError, match="agent_timeout"):
        perform(db, run.id, Slow())
    assert run.status == "failed"


def test_step_limit_and_invalid_final(db, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_STEPS", "6")
    settings.cache_clear()
    item, run = setup_run(db)
    assert perform(db, run.id, MockProvider())["status"] == "completed"  # exactly six calls
    item, run = setup_run(db, "SKU-0001, 1 шт.\nSKU-0002, 1 шт.", "limited-key")
    with pytest.raises(ProviderError, match="limit"):
        perform(db, run.id, MockProvider())
    assert run.status == "failed"


@pytest.mark.parametrize("code", [401, 429, 500])
def test_llm_http_errors_are_redacted(db, monkeypatch, code):
    monkeypatch.setenv("LLM_MODEL", "local-test-model")
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    settings.cache_clear()
    item, run = setup_run(db)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(code, json={"secret": "do not log this body"})
        )
    ) as client:
        with pytest.raises(ProviderError, match=f"provider_http_{code}"):
            perform(db, run.id, CompatibleProvider(client))
    view = json.dumps(run_view(db, run), ensure_ascii=False)
    assert "do not log" not in view and "not-a-real-key" not in view
    assert run.status == "failed"


def test_compatible_real_tool_protocol_and_token_usage(db, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "local-test-model")
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    settings.cache_clear()
    mock = MockProvider()
    extraction, _ = mock.extract("SKU-0001, 2 шт.")
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "tools" not in payload:
            message = {"content": extraction.model_dump_json()}
        else:
            reply = mock.reply(payload["messages"], payload["tools"])
            message = {
                "content": reply.content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in reply.calls
                ],
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    item, run = setup_run(db)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert perform(db, run.id, CompatibleProvider(client))["status"] == "completed"
    assert any(
        any(m["role"] == "tool" and "tool_call_id" in m for m in r["messages"]) for r in requests
    )
    assert all(
        c.usage["total_tokens"] == 15
        for c in db.scalars(select(AgentCall).where(AgentCall.kind == "provider"))
    )
    assert db.get(Inquiry, item.id).confirmed_revision is None


def test_llm_timeout_and_invalid_schema(db, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "local-test-model")
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    settings.cache_clear()

    def timeout(request):
        raise httpx.ReadTimeout("timeout")

    item, run = setup_run(db)
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ProviderError, match="provider_timeout"):
            perform(db, run.id, CompatibleProvider(client))
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []}))
    ) as client:
        with pytest.raises(ProviderError, match="invalid_extraction_schema"):
            perform(db, run.id, CompatibleProvider(client))


def test_rq_queue_executes_once_and_api_can_poll(manager, db, monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr("app.processing.connection", lambda **kwargs: redis)
    monkeypatch.setattr("app.processing.engine", lambda: db.get_bind())
    identifier = manager.post(
        "/api/inquiries",
        json={"customer_id": 1, "text": "SKU-0001, 2 шт."},
        headers={"Idempotency-Key": "queue-inquiry-key"},
    ).json()["id"]
    url = f"/api/inquiries/{identifier}/process"
    response = manager.post(url, json={}, headers={"Idempotency-Key": "queue-process-key"})
    assert response.status_code == 202, response.text
    assert (
        manager.post(url, json={}, headers={"Idempotency-Key": "queue-process-key"}).json()["id"]
        == response.json()["id"]
    )
    queue = Queue("proposals", connection=redis, serializer=JSONSerializer)
    assert len(queue) == 1

    class LocalWorker(SimpleWorker):
        death_penalty_class = TimerDeathPenalty

    LocalWorker([queue], connection=redis, serializer=JSONSerializer).work(burst=True)
    db.expire_all()
    result = manager.get(f"/api/inquiries/{identifier}/runs").json()[0]
    assert result["status"] == "completed", result
    assert result["result"]["revision"] == 1
    assert len(result["calls"]) >= 6
    assert (
        manager.post(url, json={}, headers={"Idempotency-Key": "queue-process-key"}).json()[
            "status"
        ]
        == "completed"
    )
    assert len(queue) == 0


def test_queue_outage_preserves_durable_run(manager, db, monkeypatch):
    from redis.exceptions import ConnectionError

    def unavailable():
        raise ConnectionError()

    monkeypatch.setattr("app.processing.connection", unavailable)
    item, _ = setup_run(db)
    # Use the existing durable key to exercise dispatch after a queue outage.
    response = manager.post(
        f"/api/inquiries/{item.id}/process", json={}, headers={"Idempotency-Key": "agent-test-key"}
    )
    assert response.status_code == 503
    assert db.scalar(select(func.count()).select_from(ProcessingRun)) == 1


def test_rq_transient_failure_retries_without_duplicate_quote(db, monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr("app.processing.connection", lambda **kwargs: redis)
    monkeypatch.setattr("app.processing.engine", lambda: db.get_bind())

    class Flaky(MockProvider):
        failures = 1

        def extract(self, text):
            if self.failures:
                self.failures -= 1
                raise ProviderError("provider_http_429")
            return super().extract(text)

    selected = Flaky()
    monkeypatch.setattr("app.processing.provider", lambda: selected)
    item, run = setup_run(db)
    dispatch(db, run)
    queue = Queue("proposals", connection=redis, serializer=JSONSerializer)
    worker = SimpleWorker([queue], connection=redis, serializer=JSONSerializer)
    worker.death_penalty_class = TimerDeathPenalty
    worker.work(burst=True)
    db.refresh(run)
    assert run.status == "completed" and run.attempt == 2
    assert db.scalar(select(func.count()).select_from(QuoteVersion)) == 1


def test_worker_losing_lease_cannot_create_or_overwrite_new_claim(db):
    item, run = setup_run(db)

    class LeaseLost(MockProvider):
        def reply(self, messages, tools):
            db.execute(
                update(ProcessingRun)
                .where(ProcessingRun.id == run.id)
                .values(claim_token="new-worker-claim")
            )
            db.commit()
            return super().reply(messages, tools)

    assert perform(db, run.id, LeaseLost())["duplicate"]
    db.refresh(run)
    assert run.claim_token == "new-worker-claim" and run.status == "running"
    assert db.scalar(select(func.count()).select_from(QuoteVersion)) == 0
