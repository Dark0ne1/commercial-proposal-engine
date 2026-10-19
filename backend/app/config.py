from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://proposal:proposal@db:5432/proposal"
    storage_dir: Path = Path("storage")
    public_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    vat_rate: Decimal = Field(default=Decimal("20"), ge=0, le=100)
    max_discount: Decimal = Field(default=Decimal("15"), ge=0, le=100)
    validity_days: int = Field(default=14, ge=1, le=365)
    supplier_name: str = "ООО «Демо Промснаб» (вымышленная компания)"
    supplier_details: str = "Демонстрационные реквизиты • ИНН 0000000000 • demo@example.test"
    libreoffice_bin: str = "soffice"
    render_timeout: int = Field(default=90, ge=1, le=180)
    llm_provider: Literal["mock", "compatible"] = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout: int = Field(default=20, ge=1, le=60)
    agent_max_steps: int = Field(default=30, ge=6, le=100)
    agent_timeout: int = Field(default=120, ge=10, le=300)
    redis_url: str = "redis://redis:6379/0"
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)


@lru_cache
def settings() -> Settings:
    return Settings()
