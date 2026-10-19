import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import app
from app.config import settings
from app.infrastructure import password_hash, session
from app.models import Base, Customer, Product, User


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    executable = Path("C:/Program Files/LibreOffice/program/soffice.com")
    if executable.exists():
        monkeypatch.setenv("LIBREOFFICE_BIN", str(executable))
    settings.cache_clear()
    url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    options = (
        {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        if url == "sqlite://"
        else {}
    )
    engine = create_engine(url, **options)
    # TEST_DATABASE_URL must point to a disposable test database.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all(
            [
                User(
                    id=1, email="manager@example.test", password=password_hash("demo-password-123")
                ),
                Customer(
                    id=1,
                    name="ООО Тест",
                    details="Вымышленные реквизиты",
                    discount=5,
                    payment_terms="100% аванс",
                ),
                Product(
                    id=1,
                    sku="SKU-0001",
                    name="Клапан Ду25 сталь",
                    unit="шт",
                    price="100.01",
                    stock=5,
                    lead_days=14,
                    production_days=8,
                    delivery_days=6,
                ),
                Product(
                    id=2,
                    sku="SKU-0002",
                    name="Клапан Ду25 нержавеющий",
                    unit="шт",
                    price="200.00",
                    stock=0,
                    lead_days=21,
                    production_days=14,
                    delivery_days=7,
                ),
            ]
        )
        db.commit()
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()
    settings.cache_clear()


@pytest.fixture
def client(db):
    app.dependency_overrides[session] = lambda: db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def manager(client):
    result = client.post(
        "/api/login", json={"email": "manager@example.test", "password": "demo-password-123"}
    )
    assert result.status_code == 200
    return client
