import logging
import re
import secrets
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, Header, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app import application as service
from app.config import settings
from app.documents import artifact_directory, generate_documents
from app.domain import Approval, DraftInput, Input, InquiryInput
from app.infrastructure import password_hash, session, token_hash, verify_password
from app.intake import store_upload
from app.models import Customer, Inquiry, LoginSession, ProcessingRun, Product, User, as_utc, now
from app.processing import ProcessInput, create_run, dispatch, run_view

logging.basicConfig(level=logging.INFO)
DUMMY_PASSWORD = password_hash("unavailable", "fixed-dummy-salt")
app = FastAPI(title="Commercial Proposal Engine", version="0.1.0")
DB = Annotated[Session, Depends(session)]
Key = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
]


@app.exception_handler(service.Problem)
async def problem_handler(request, error):
    return JSONResponse(status_code=error.status, content={"detail": error.message})


@app.exception_handler(IntegrityError)
@app.exception_handler(StaleDataError)
async def conflict_handler(request, error):
    return JSONResponse(
        status_code=409,
        content={"detail": "Конкурентное изменение. Повторите запрос с тем же ключом"},
    )


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        allowed_origins = {settings().public_origin}
        local = re.fullmatch(r"http://(?:localhost|127\.0\.0\.1)(:\d+)?", settings().public_origin)
        if local:
            allowed_origins.update(
                f"http://{host}{local[1] or ''}" for host in ("localhost", "127.0.0.1")
            )
        if origin and origin not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Недопустимый Origin"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def manager(request: Request, db: DB) -> User:
    token = request.cookies.get("proposal_session", "")
    login = db.get(LoginSession, token_hash(token))
    if not login or as_utc(login.expires) <= now():
        raise service.Problem(401, "Войдите в аккаунт менеджера")
    return service.require(db, User, login.user_id)


Manager = Annotated[User, Depends(manager)]


class Login(Input):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@app.get("/api/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "mode": settings().llm_provider, "ai_enabled": True}


@app.post("/api/login")
def login(data: Login, db: DB, response: Response):
    user = db.scalar(select(User).where(User.email == data.email))
    # Also perform the expensive KDF for unknown users.
    stored = user.password if user else DUMMY_PASSWORD
    valid = verify_password(data.password, stored)
    if not user or not valid:
        raise service.Problem(401, "Неверный email или пароль")
    db.execute(delete(LoginSession).where(LoginSession.expires < now()))
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token=token_hash(token),
            user_id=user.id,
            expires=now() + timedelta(hours=settings().session_hours),
        )
    )
    db.commit()
    response.set_cookie(
        "proposal_session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="strict",
        max_age=settings().session_hours * 3600,
        path="/",
    )
    return {"email": user.email}


@app.post("/api/logout")
def logout(request: Request, response: Response, db: DB, user: Manager):
    db.execute(
        delete(LoginSession).where(
            LoginSession.token == token_hash(request.cookies.get("proposal_session", ""))
        )
    )
    db.commit()
    response.delete_cookie("proposal_session", path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user: Manager):
    return {"email": user.email, "mode": settings().llm_provider}


@app.get("/api/customers")
def customers(db: DB, user: Manager):
    return [
        {
            "id": c.id,
            "name": c.name,
            "details": c.details,
            "discount": str(c.discount),
            "discount_kind": c.discount_kind,
            "payment_terms": c.payment_terms,
        }
        for c in db.scalars(select(Customer).order_by(Customer.id))
    ]


@app.get("/api/catalog")
def catalog(db: DB, user: Manager, q: Annotated[str, Field(max_length=200)] = ""):
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    statement = select(Product).where(
        (Product.name.ilike(f"%{escaped}%", escape="\\"))
        | (Product.sku.ilike(f"%{escaped}%", escape="\\"))
    )
    return [
        {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "unit": p.unit,
            "price": str(p.price),
            "stock": str(p.stock),
            "lead_days": p.lead_days,
            "production_days": p.production_days,
            "delivery_days": p.delivery_days,
        }
        for p in db.scalars(statement.order_by(Product.id).limit(150))
    ]


@app.get("/api/inquiries")
def inquiries(db: DB, user: Manager):
    return [
        {
            "id": i.id,
            "customer_id": i.customer_id,
            "text": i.text[:180],
            "revision": i.revision,
            "confirmed_revision": i.confirmed_revision,
            "created_at": as_utc(i.created_at).isoformat(),
        }
        for i in db.scalars(select(Inquiry).order_by(Inquiry.created_at.desc()).limit(100))
    ]


@app.post("/api/inquiries", status_code=201)
def create_inquiry(data: InquiryInput, key: Key, db: DB, user: Manager):
    return service.describe(db, service.create_inquiry(db, data, key, user.email))


@app.post("/api/inquiries/import", status_code=201)
async def import_inquiry(
    db: DB,
    user: Manager,
    key: Key,
    file: Annotated[UploadFile, File()],
    customer_id: Annotated[int, Form(gt=0)],
    text: Annotated[str, Form(max_length=20000)] = "",
):
    content = bytearray()
    try:
        while chunk := await file.read(64 * 1024):
            content.extend(chunk)
            if len(content) > settings().upload_max_bytes:
                raise service.Problem(413, "Превышен лимит файла")
        item = store_upload(
            db, customer_id, file.filename or "", bytes(content), key, user.email, text
        )
        return service.describe(db, item)
    finally:
        await file.close()


@app.post("/api/inquiries/{identifier}/process", status_code=202)
def process_inquiry(identifier: str, data: ProcessInput, key: Key, db: DB, user: Manager):
    run = create_run(db, identifier, data, key, user.email)
    dispatch(db, run)
    return run_view(db, run)


@app.get("/api/inquiries/{identifier}/runs")
def runs(identifier: str, db: DB, user: Manager):
    service.inquiry(db, identifier)
    return [
        run_view(db, run)
        for run in db.scalars(
            select(ProcessingRun)
            .where(ProcessingRun.inquiry_id == identifier)
            .order_by(ProcessingRun.created_at.desc())
            .limit(20)
        )
    ]


@app.post("/api/inquiries/{identifier}/runs/{run_id}/retry", status_code=202)
def retry_run(identifier: str, run_id: str, db: DB, user: Manager):
    item = service.inquiry(db, identifier)
    run = service.require(db, ProcessingRun, run_id)
    if run.inquiry_id != identifier:
        raise service.Problem(404, "Задача не найдена")
    if item.confirmed_revision or item.revision != run.base_revision:
        raise service.Problem(409, "Версия КП изменилась; повтор обработки остановлен")
    dispatch(db, run)
    return run_view(db, run)


@app.get("/api/inquiries/{identifier}")
def get_inquiry(identifier: str, db: DB, user: Manager):
    return service.describe(db, service.inquiry(db, identifier))


@app.post("/api/inquiries/{identifier}/versions", status_code=201)
def draft(identifier: str, data: DraftInput, key: Key, db: DB, user: Manager):
    version = service.create_version(db, identifier, data, key, user.email)
    return {"revision": version.revision, "snapshot": version.snapshot}


@app.post("/api/inquiries/{identifier}/confirm")
def confirm(identifier: str, data: Approval, db: DB, user: Manager):
    service.approve(db, identifier, data.revision, user.email)
    return generate_documents(db, identifier, user.email)


@app.post("/api/inquiries/{identifier}/documents")
def documents(identifier: str, db: DB, user: Manager):
    return generate_documents(db, identifier, user.email)


@app.get("/api/inquiries/{identifier}/files/{extension}")
def download(identifier: str, extension: Literal["docx", "pdf"], db: DB, user: Manager):
    item = service.inquiry(db, identifier)
    if not item.confirmed_revision:
        raise service.Problem(409, "КП ещё не подтверждено")
    version = service.version_at(db, identifier, item.confirmed_revision)
    path = artifact_directory(version.id) / f"proposal.{extension}"
    if not path.is_file():
        raise service.Problem(404, "Документ не создан. Повторите генерацию")
    media = (
        "application/pdf"
        if extension == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(
        path, media_type=media, filename=f"quote-{identifier[:8]}-v{version.revision}.{extension}"
    )
