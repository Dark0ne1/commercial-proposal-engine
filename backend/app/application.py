import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import DraftInput, InquiryInput, calculate, money
from app.models import AuditEvent, Customer, Inquiry, Product, QuoteVersion, as_utc


class Problem(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def fingerprint(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require(db: Session, model, identifier):
    entity = db.get(model, identifier)
    if entity is None:
        raise Problem(404, "Объект не найден")
    return entity


def inquiry(db: Session, identifier: str, lock=False) -> Inquiry:
    statement = select(Inquiry).where(Inquiry.id == identifier)
    if lock:
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise Problem(404, "Заявка не найдена")
    return item


def event(db, item, actor, action, details=None):
    db.add(AuditEvent(inquiry_id=item.id, actor=actor, action=action, details=details or {}))


def create_inquiry(db, data: InquiryInput, key: str, actor: str, source_info=None):
    content = data.model_dump(mode="json")
    if source_info:
        content["source"] = source_info
    digest = fingerprint(content)
    previous = db.scalar(select(Inquiry).where(Inquiry.create_key == key))
    if previous:
        if previous.fingerprint != digest:
            raise Problem(409, "Этот ключ уже использован с другими данными")
        return previous
    require(db, Customer, data.customer_id)
    item = Inquiry(
        id=str(uuid4()),
        customer_id=data.customer_id,
        text=data.text,
        create_key=key,
        fingerprint=digest,
        revision=0,
        source_info=source_info,
    )
    db.add(item)
    db.flush()
    event(db, item, actor, "inquiry.created")
    db.commit()
    return item


def create_version(db, identifier: str, data: DraftInput, key: str, actor: str):
    item = inquiry(db, identifier, lock=True)
    digest = fingerprint({"inquiry_id": identifier, **data.model_dump(mode="json")})
    previous = db.scalar(select(QuoteVersion).where(QuoteVersion.operation_key == key))
    if previous:
        if previous.fingerprint != digest:
            raise Problem(409, "Этот ключ уже использован с другими данными")
        return previous
    if item.confirmed_revision:
        raise Problem(409, "Подтверждённое КП неизменно. Создайте новую заявку")
    if item.revision != data.expected_revision:
        raise Problem(409, "Черновик изменился. Обновите заявку")
    config = settings()
    if data.discount > config.max_discount:
        raise Problem(422, f"Максимальная скидка {config.max_discount}%")
    customer = require(db, Customer, item.customer_id)
    quantities = defaultdict(Decimal)
    for entry in data.lines:
        quantities[entry.product_id] += entry.quantity
    lines = []
    for entry in data.lines:
        product = require(db, Product, entry.product_id)
        if product.unit != entry.unit:
            raise Problem(422, f"{product.sku}: допустимая единица — {product.unit}")
        price = money(product.price if entry.unit_price is None else entry.unit_price)
        lines.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "unit": product.unit,
                "quantity": format(entry.quantity, "f"),
                "catalog_price": str(product.price),
                "unit_price": str(price),
                "stock": str(product.stock),
                "lead_days": product.lead_days,
                "production_days": product.production_days,
                "delivery_days": product.delivery_days,
                "availability": "В наличии"
                if quantities[entry.product_id] <= product.stock
                else f"Под заказ, {product.lead_days} дн.",
            }
        )
    revision = item.revision + 1
    snapshot = {
        **calculate(lines, data.discount, config.vat_rate),
        "number": f"КП-{identifier[:8].upper()}-{revision}",
        "date": date.today().isoformat(),
        "valid_until": (date.today() + timedelta(days=config.validity_days)).isoformat(),
        "supplier": {"name": config.supplier_name, "details": config.supplier_details},
        "customer": {"id": customer.id, "name": customer.name, "details": customer.details},
        "payment_terms": data.payment_terms,
        "discount_kind": customer.discount_kind
        if data.discount == customer.discount
        else "manager_override",
        "comments": data.comments,
        "notice": "Демонстрационные данные. Наличие справочное, товар не резервируется.",
    }
    version = QuoteVersion(
        id=str(uuid4()),
        inquiry_id=item.id,
        revision=revision,
        snapshot=snapshot,
        operation_key=key,
        fingerprint=digest,
    )
    db.add(version)
    item.revision = revision
    event(db, item, actor, "quote.drafted", {"revision": revision, "snapshot": snapshot})
    db.commit()
    return version


def version_at(db, identifier, revision):
    version = db.scalar(
        select(QuoteVersion).where(
            QuoteVersion.inquiry_id == identifier, QuoteVersion.revision == revision
        )
    )
    if version is None:
        raise Problem(404, "Версия КП не найдена")
    return version


def approve(db, identifier, revision, actor):
    item = inquiry(db, identifier, lock=True)
    if item.confirmed_revision == revision:
        return item
    if item.confirmed_revision or item.revision != revision:
        raise Problem(409, "Можно подтвердить только текущую неподтверждённую версию")
    version_at(db, identifier, revision)
    item.confirmed_revision = revision
    event(db, item, actor, "quote.confirmed", {"revision": revision})
    db.commit()
    return item


def describe(db, item):
    versions = db.scalars(
        select(QuoteVersion)
        .where(QuoteVersion.inquiry_id == item.id)
        .order_by(QuoteVersion.revision)
    ).all()
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.inquiry_id == item.id).order_by(AuditEvent.id)
    ).all()
    return {
        "id": item.id,
        "customer_id": item.customer_id,
        "text": item.text,
        "source_info": {k: v for k, v in (item.source_info or {}).items() if k != "path"},
        "extracted_text": item.extracted_text,
        "revision": item.revision,
        "confirmed_revision": item.confirmed_revision,
        "versions": [{"revision": v.revision, "snapshot": v.snapshot} for v in versions],
        "events": [
            {
                "action": e.action,
                "actor": e.actor,
                "details": e.details,
                "at": as_utc(e.created_at).isoformat(),
            }
            for e in events
        ],
    }
