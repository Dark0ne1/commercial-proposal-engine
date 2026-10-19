import hashlib
import hmac
import secrets
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings


@lru_cache
def engine():
    url = settings().database_url
    return create_engine(
        url,
        pool_pre_ping=True,
        **({"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}),
    )


def session():
    with Session(engine(), expire_on_commit=False) as db:
        yield db


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000)
    return f"{salt}${value.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt = stored.split("$")[0]
    return hmac.compare_digest(password_hash(password, salt), stored)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
