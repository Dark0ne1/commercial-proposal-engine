"""Deterministic synthetic demo dataset. Run only against an explicitly chosen database."""

import argparse
import os
import random
from datetime import datetime, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.application import create_version, event, fingerprint
from app.domain import DraftInput, InquiryInput, LineInput
from app.infrastructure import engine, password_hash
from app.models import (
    AgentCall,
    AuditEvent,
    Customer,
    Inquiry,
    LoginSession,
    ProcessingRun,
    Product,
    QuoteVersion,
    User,
)

PAYMENTS = ["100% предоплата", "50% аванс, 50% перед отгрузкой", "Оплата в течение 10 дней"]
INQUIRIES = [
    "Просим выставить счёт на SKU-0001, 10 шт.",
    "Нужен клапан Ду25, материал не указан — уточнить исполнение.",
    "Нужен космический насос ZX-UNKNOWN, 2 шт. — вне каталога.",
    "Прошу 0 шт. SKU-0001 — количество требует исправления.",
    "Нужно -5 м трубы — отрицательное количество.",
    "SKU-0001, 3 кг — неверная единица, требуется шт.",
    "Нужны фильтры, характеристики и количество уточним.",
    "SKU-0150, 10000 шт., нужна поставка под заказ.",
    "Проверьте цену клапана из прошлого КП; без согласования не менять.",
    "Нужно 2.500 м SKU-0005, оплата по согласованию.",
]


def uid(kind, index):
    return str(uuid5(NAMESPACE_URL, f"proposal-engine-demo/{kind}/{index}"))


def seed(db: Session, password: str, reset=False):
    if len(password) < 12:
        raise ValueError("DEMO_PASSWORD должен содержать минимум 12 символов")
    if reset:
        for model in (
            AgentCall,
            ProcessingRun,
            AuditEvent,
            QuoteVersion,
            Inquiry,
            LoginSession,
            Product,
            Customer,
            User,
        ):
            db.execute(delete(model))
        db.commit()
    if db.scalar(select(func.count()).select_from(Customer)):
        counts = [
            db.scalar(select(func.count()).select_from(model))
            for model in (Customer, Product, Inquiry, QuoteVersion)
        ]
        if any(
            actual < expected for actual, expected in zip(counts, [50, 150, 40, 20], strict=True)
        ):
            raise ValueError(
                "База непустая или seed неполный; используйте отдельную демобазу либо явный reset"
            )
        return {"status": "already_seeded"}
    rng = random.Random(20261019)
    db.add(User(id=1, email="manager@example.test", password=password_hash(password)))
    for index in range(1, 51):
        db.add(
            Customer(
                id=index,
                name=f"ООО «Демо {'Механика' if index % 2 else 'Промдеталь'} {index:02}»",
                details=f"Вымышленный клиент №{index}; ИНН DEMO-{index:04}; client{index}@example.test",
                discount=Decimal([0, 3, 5, 7][index % 4]),
                discount_kind=["none", "contract", "partner", "individual"][index % 4],
                payment_terms=PAYMENTS[index % 3],
            )
        )
    families = ["Клапан", "Фильтр", "Фланец", "Насос", "Труба"]
    for index in range(1, 151):
        family = families[(index - 1) % 5]
        production_days = [7, 14, 21][index % 3]
        delivery_days = [2, 4, 7][index % 3]
        db.add(
            Product(
                id=index,
                sku=f"SKU-{index:04}",
                name=f"{family} Ду{[25, 50, 80][((index - 1) // 5) % 3]} {['сталь', 'нержавеющая сталь'][index % 2]} исполнение {((index - 1) // 30) + 1}",
                unit="м" if family == "Труба" else "шт",
                price=Decimal(rng.randrange(15000, 850000)) / 100,
                stock=Decimal(rng.randrange(0, 80)),
                lead_days=production_days + delivery_days,
                production_days=production_days,
                delivery_days=delivery_days,
            )
        )
    db.flush()
    for index in range(1, 41):
        data = InquiryInput(customer_id=index, text=INQUIRIES[(index - 1) % 10])
        item = Inquiry(
            id=uid("inquiry", index),
            customer_id=index,
            text=data.text,
            create_key=f"seed-inquiry-{index}",
            fingerprint=fingerprint(data.model_dump()),
            created_at=datetime(2026, 10, 1, 9, index, tzinfo=timezone.utc),
            revision=0,
        )
        db.add(item)
        db.flush()
        event(db, item, "seed", "inquiry.created", {"synthetic": True})
    db.commit()
    # Historical quotes are separate valid manual resolutions, including clarified requests.
    for index in range(1, 21):
        customer = db.get(Customer, index)
        product = db.get(Product, index)
        version = create_version(
            db,
            uid("inquiry", index),
            DraftInput(
                expected_revision=0,
                lines=[LineInput(product_id=index, quantity="10", unit=product.unit)],
                discount=customer.discount,
                payment_terms=customer.payment_terms,
                comments="Синтетическое историческое КП; характеристики уточнены менеджером.",
            ),
            f"seed-quote-{index}",
            "seed",
        )
        version.created_at = datetime(2026, 10, 2, 10, index, tzinfo=timezone.utc)
        version.snapshot = {**version.snapshot, "date": "2026-10-02", "valid_until": "2026-10-16"}
        version.id = uid("quote", fingerprint(version.snapshot))
        drafted_event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.inquiry_id == version.inquiry_id, AuditEvent.action == "quote.drafted"
            )
        )
        drafted_event.details = {"revision": 1, "snapshot": version.snapshot}
        item = db.get(Inquiry, uid("inquiry", index))
        item.confirmed_revision = 1
        event(db, item, "seed", "quote.confirmed", {"revision": 1, "synthetic": True})
        db.commit()
    return {"customers": 50, "products": 150, "inquiries": 40, "historical_quotes": 20}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-demo", action="store_true", help="Удаляет ВСЕ данные выбранной БД")
    parser.add_argument("--confirm-reset", action="store_true")
    args = parser.parse_args()
    if args.reset_demo and not args.confirm_reset:
        parser.error("Сброс требует --confirm-reset; используйте только отдельную демобазу")
    with Session(engine(), expire_on_commit=False) as db:
        print(seed(db, os.environ.get("DEMO_PASSWORD", ""), args.reset_demo))
