import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import app
from app.infrastructure import session
from app.models import QuoteVersion


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="Requires real PostgreSQL row locks",
)
def test_concurrent_versions(manager, db):
    engine = db.get_bind()

    def independent_session():
        with Session(engine, expire_on_commit=False) as connection:
            yield connection

    app.dependency_overrides[session] = independent_session
    identifier = manager.post(
        "/api/inquiries",
        headers={"Idempotency-Key": "parallel-inquiry"},
        json={"customer_id": 1, "text": "Concurrent quote"},
    ).json()["id"]

    def save(index):
        return manager.post(
            f"/api/inquiries/{identifier}/versions",
            headers={"Idempotency-Key": f"parallel-draft-{index}"},
            json={
                "expected_revision": 0,
                "lines": [{"product_id": 1, "quantity": "1", "unit": "шт"}],
                "discount": "0",
                "payment_terms": "Аванс",
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, [1, 2])) == [201, 409]
    assert db.scalar(select(func.count()).select_from(QuoteVersion)) == 1
