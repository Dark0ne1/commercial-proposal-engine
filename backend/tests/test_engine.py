import shutil
import subprocess
from decimal import Decimal
from io import BytesIO

import pytest
from docx import Document
from pypdf import PdfReader
from sqlalchemy import func, select

from app.config import settings
from app.domain import calculate
from app.models import AuditEvent, Customer, Inquiry, Product, QuoteVersion
from seed import seed


# Ten golden numeric scenarios; expected values are independent constants.
@pytest.mark.parametrize(
    "price,quantity,discount,vat,net,tax,total",
    [
        ("100", "2", "0", "20", "200.00", "40.00", "240.00"),
        ("100", "2", "5", "20", "190.00", "38.00", "228.00"),
        ("100", "1", "10", "0", "90.00", "0.00", "90.00"),
        ("100", "1", "100", "20", "0.00", "0.00", "0.00"),
        ("0", "2", "5", "20", "0.00", "0.00", "0.00"),
        ("0.05", "1", "10", "20", "0.04", "0.01", "0.05"),
        ("12.34", "2.5", "0", "20", "30.85", "6.17", "37.02"),
        ("99.99", "3", "7", "20", "278.97", "55.79", "334.76"),
        ("1.01", "0.5", "0", "10", "0.51", "0.05", "0.56"),
        ("999999.99", "1000", "15", "20", "849999991.50", "169999998.30", "1019999989.80"),
    ],
)
def test_golden_calculation(price, quantity, discount, vat, net, tax, total):
    result = calculate(
        [{"unit_price": price, "quantity": quantity}], Decimal(discount), Decimal(vat)
    )
    assert (result["net"], result["vat"], result["total"]) == (net, tax, total)


def create(client, key="inquiry-key-01", **changes):
    response = client.post(
        "/api/inquiries",
        json={"customer_id": 1, "text": "Клапан 2 шт.", **changes},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def payload(**changes):
    return {
        "expected_revision": 0,
        "lines": [{"product_id": 1, "quantity": "2", "unit": "шт"}],
        "discount": "5",
        "payment_terms": "100% предоплата",
        "comments": "Проверено",
        **changes,
    }


def draft(client, identifier, key="draft-key-01", **changes):
    return client.post(
        f"/api/inquiries/{identifier}/versions",
        json=payload(**changes),
        headers={"Idempotency-Key": key},
    )


def test_auth_origin_and_logout(client):
    assert client.get("/api/customers").status_code == 401
    assert (
        client.post("/api/login", json={"email": "x@y.z", "password": "wrong"}).status_code == 401
    )
    assert (
        client.post(
            "/api/login",
            json={"email": "manager@example.test", "password": "demo-password-123"},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/login", json={"email": "manager@example.test", "password": "demo-password-123"}
    )
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/me").status_code == 200
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "configured", ["http://localhost:3000", "http://127.0.0.1:3000", "https://app.example.test"]
)
@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "https://localhost:3000",
        "http://localhost.evil.test:3000",
        "https://app.example.test",
        "null",
    ],
)
def test_origin_loopback_aliases_only_for_local_http(client, monkeypatch, configured, origin):
    monkeypatch.setenv("PUBLIC_ORIGIN", configured)
    settings.cache_clear()
    allowed = origin == configured or (
        configured.startswith("http://")
        and origin in {"http://localhost:3000", "http://127.0.0.1:3000"}
    )
    result = client.post(
        "/api/login", headers={"Origin": origin}, json={"email": "x@y.z", "password": "wrong"}
    )
    assert result.status_code == (401 if allowed else 403)


def test_seed_counts_and_repeatability(db):
    first = seed(db, "demo-password-123", reset=True)

    def rows():
        return [
            (p.sku, p.name, str(p.price), str(p.stock))
            for p in db.scalars(select(Product).order_by(Product.id))
        ]

    expected = rows()
    assert set(db.scalars(select(Customer.discount_kind))) == {
        "none",
        "contract",
        "partner",
        "individual",
    }
    assert all(
        p.production_days + p.delivery_days == p.lead_days for p in db.scalars(select(Product))
    )
    for model, count in [(Customer, 50), (Product, 150), (Inquiry, 40), (QuoteVersion, 20)]:
        assert db.scalar(select(func.count()).select_from(model)) == count
    assert seed(db, "demo-password-123")["status"] == "already_seeded"
    assert seed(db, "demo-password-123", reset=True) == first
    assert rows() == expected


def test_catalog_ambiguity_and_literal_search(manager):
    products = manager.get("/api/catalog", params={"q": "Ду25"}).json()
    assert len(products) == 2  # Never automatically choose the first match.
    assert manager.get("/api/catalog", params={"q": "NOT-IN-CATALOG"}).json() == []
    assert manager.get("/api/catalog", params={"q": "%"}).json() == []


def test_seed_refuses_partial_database(db):
    with pytest.raises(ValueError, match="seed"):
        seed(db, "demo-password-123")


def test_idempotency_and_conflicts(manager, db):
    identifier = create(manager)
    assert create(manager) == identifier
    assert (
        manager.post(
            "/api/inquiries",
            json={"customer_id": 1, "text": "changed"},
            headers={"Idempotency-Key": "inquiry-key-01"},
        ).status_code
        == 409
    )
    first = draft(manager, identifier)
    assert first.status_code == 201
    assert draft(manager, identifier).json() == first.json()
    assert draft(manager, identifier, discount="3").status_code == 409
    assert draft(manager, identifier, key="draft-key-stale").status_code == 409
    assert db.scalar(select(func.count()).select_from(QuoteVersion)) == 1
    assert manager.get(f"/api/inquiries/{identifier}").json()["revision"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"lines": [{"product_id": 1, "quantity": "0", "unit": "шт"}]},
        {"lines": [{"product_id": 1, "quantity": "-1", "unit": "шт"}]},
        {"lines": [{"product_id": 1, "quantity": "1.0001", "unit": "шт"}]},
        {"lines": [{"product_id": 1, "quantity": "NaN", "unit": "шт"}]},
        {"lines": [{"product_id": 1, "quantity": "1", "unit": "кг"}]},
        {"discount": "16"},
        {"lines": []},
        {"extra_field": "forbidden"},
    ],
)
def test_validation(manager, changes):
    identifier = create(manager)
    assert draft(manager, identifier, **changes).status_code == 422


def test_unknown_product_and_customer(manager):
    assert (
        manager.post(
            "/api/inquiries",
            json={"customer_id": 999, "text": "test"},
            headers={"Idempotency-Key": "unknown-customer"},
        ).status_code
        == 404
    )
    identifier = create(manager)
    assert (
        draft(
            manager, identifier, lines=[{"product_id": 999, "quantity": "1", "unit": "шт"}]
        ).status_code
        == 404
    )


def test_snapshots_versions_and_manual_override(manager, db):
    identifier = create(manager)
    assert draft(manager, identifier).status_code == 201
    db.get(Product, 1).price = Decimal("999.99")
    db.get(Customer, 1).name = "Изменённый клиент"
    db.commit()
    assert (
        draft(
            manager,
            identifier,
            key="draft-key-v2",
            expected_revision=1,
            lines=[{"product_id": 1, "quantity": "6", "unit": "шт", "unit_price": "90.00"}],
        ).status_code
        == 201
    )
    data = manager.get(f"/api/inquiries/{identifier}").json()
    assert data["versions"][0]["snapshot"]["lines"][0]["unit_price"] == "100.01"
    assert data["versions"][0]["snapshot"]["customer"]["name"] == "ООО Тест"
    latest = data["versions"][1]["snapshot"]
    assert latest["lines"][0]["unit_price"] == "90.00"
    assert latest["lines"][0]["availability"] == "Под заказ, 14 дн."
    assert len(data["events"]) == 3
    assert data["events"][0]["at"].endswith("+00:00")
    assert data["events"][-1]["details"]["snapshot"] == latest
    assert (
        manager.post(f"/api/inquiries/{identifier}/confirm", json={"revision": 1}).status_code
        == 409
    )


def test_render_failure_is_retryable(manager, monkeypatch):
    identifier = create(manager)
    assert draft(manager, identifier).status_code == 201
    monkeypatch.setattr(
        "app.documents.render",
        lambda *args: (_ for _ in ()).throw(RuntimeError("conversion failed")),
    )
    assert (
        manager.post(f"/api/inquiries/{identifier}/confirm", json={"revision": 1}).status_code
        == 503
    )
    data = manager.get(f"/api/inquiries/{identifier}").json()
    assert data["confirmed_revision"] == 1
    assert data["events"][-1]["action"] == "documents.failed"
    assert (
        draft(manager, identifier, key="draft-after-confirm", expected_revision=1).status_code
        == 409
    )


def test_document_access_requires_confirmation(manager):
    identifier = create(manager)
    assert manager.post(f"/api/inquiries/{identifier}/documents").status_code == 409
    assert manager.get(f"/api/inquiries/{identifier}/files/pdf").status_code == 409
    assert manager.get(f"/api/inquiries/{identifier}/files/exe").status_code == 422


def test_duplicate_lines_use_combined_availability(manager):
    identifier = create(manager)
    result = draft(
        manager, identifier, lines=[{"product_id": 1, "quantity": "3", "unit": "шт"}] * 2
    )
    assert result.status_code == 201
    assert all(
        line["availability"] == "Под заказ, 14 дн." for line in result.json()["snapshot"]["lines"]
    )


def test_exponential_inputs_have_plain_decimal_snapshot(manager):
    identifier = create(manager)
    result = draft(
        manager,
        identifier,
        lines=[{"product_id": 1, "quantity": "1e3", "unit": "шт", "unit_price": "1e2"}],
    )
    assert result.status_code == 201
    line = result.json()["snapshot"]["lines"][0]
    assert line["quantity"] == "1000" and line["unit_price"] == "100.00"


def test_full_path_real_documents(manager, db):
    if not shutil.which(settings().libreoffice_bin):
        pytest.skip("LibreOffice is required for real PDF conversion")
    identifier = create(manager)
    assert draft(manager, identifier).status_code == 201
    response = manager.post(f"/api/inquiries/{identifier}/confirm", json={"revision": 1})
    assert response.status_code == 200, response.text
    docx = manager.get(response.json()["docx"])
    pdf = manager.get(response.json()["pdf"])
    doc = Document(BytesIO(docx.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Коммерческое предложение" in text and "228.02" in text
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
    assert "Коммерческое предложение" in pdf_text and "228.02" in pdf_text
    assert "Клапан" in pdf_text and "ООО Тест" in pdf_text
    assert (
        manager.post(f"/api/inquiries/{identifier}/confirm", json={"revision": 1}).status_code
        == 200
    )
    assert manager.post(f"/api/inquiries/{identifier}/documents").status_code == 200
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "quote.confirmed")
        )
        == 1
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "documents.generated")
        )
        == 1
    )


def test_conversion_timeout(manager, monkeypatch):
    identifier = create(manager)
    draft(manager, identifier)

    def timeout(*args):
        raise subprocess.TimeoutExpired("soffice", 90)

    monkeypatch.setattr("app.documents.render", timeout)
    assert (
        manager.post(f"/api/inquiries/{identifier}/confirm", json={"revision": 1}).status_code
        == 503
    )


def test_document_pagination(manager):
    if not shutil.which(settings().libreoffice_bin):
        pytest.skip("LibreOffice is required for real PDF conversion")
    identifier = create(manager)
    response = draft(
        manager, identifier, lines=[{"product_id": 1, "quantity": "2", "unit": "шт"}] * 100
    )
    assert response.status_code == 201
    result = manager.post(f"/api/inquiries/{identifier}/confirm", json={"revision": 1})
    assert result.status_code == 200
    pdf = PdfReader(BytesIO(manager.get(result.json()["pdf"]).content))
    assert len(pdf.pages) > 1
    assert "22802.40" in pdf.pages[-1].extract_text()
    assert "Наименование" in pdf.pages[1].extract_text()
