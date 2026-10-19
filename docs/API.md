# API v0.1

Базовый путь `/api`, JSON UTF-8. Для менеджера обязательна cookie
`proposal_session` (HttpOnly, SameSite=Strict, configurable Secure).
POST браузера требует совпадения Origin с PUBLIC_ORIGIN.
Health и login публичные; остальные endpoints доступны менеджеру.

| Метод и путь | Действие |
|---|---|
| GET /health | SELECT 1, mode=mock/compatible, ai_enabled=true; не проверяет Redis |
| POST /login | {email,password}, установить сессию |
| POST /logout | Удалить сессию и cookie |
| GET /me | Текущий менеджер |
| GET /customers | Все 50 клиентов demo |
| GET /catalog?q= | До 150 позиций, literal substring; несколько совпадений не разрешаются автоматически |
| GET /inquiries | Последние 100 заявок |
| POST /inquiries | Создать; обязательный Idempotency-Key |
| POST /inquiries/import | multipart customer_id, file, необязательный text; Idempotency-Key; сохранить исходный файл |
| GET /inquiries/{id} | Исходный текст, версии со снимками, audit |
| POST /inquiries/{id}/process | {clarification?:string}; Idempotency-Key; 202 и durable run |
| GET /inquiries/{id}/runs | До 20 обработок, extraction/result/questions/errors и tools/duration/usage |
| POST /inquiries/{id}/runs/{run_id}/retry | Идемпотентная постановка того же run; без дублирования черновика |
| POST /inquiries/{id}/versions | Новый черновик; Idempotency-Key и expected_revision |
| POST /inquiries/{id}/confirm | {revision}; commit подтверждения, затем генерация |
| POST /inquiries/{id}/documents | Повторяемая генерация подтверждённой версии |
| GET /inquiries/{id}/files/docx | Защищённый DOCX |
| GET /inquiries/{id}/files/pdf | Защищённый PDF |

Создание: `{"customer_id":1,"text":"Клапан 2 шт."}`.
Версия:

```json
{
  "expected_revision": 0,
  "lines": [{"product_id":1,"quantity":"2","unit":"шт","unit_price":"100.00"}],
  "discount":"5",
  "payment_terms":"100% предоплата",
  "comments":"Проверено менеджером"
}
```

`unit_price` можно опустить: используется текущая цена каталога. Любая ручная
цена записывается вместе с исходной каталоговой в версии/audit; применение
к итоговому КП требует confirm менеджера. Глобальный каталог через API не меняется.
Деньги и количества передавайте строками. Неизвестные поля запрещены.

Idempotency-Key: 8–100 ASCII букв/цифр/_/-. Повтор с тем же содержимым
возвращает ту же запись; другое содержимое — 409. При timeout повторяйте
тот же ключ. Неверная единица/количество/скидка — 422; неизвестный объект —
404; stale revision/подтверждённая версия — 409; нет сессии — 401;
ошибка рендера — 503 с сохранённым подтверждением. После 503 используйте
POST documents. Download не запускает дорогостоящую генерацию.

`POST process` с `{}` разбирает исходный текст/документ. `clarification` — полный
заменяющий перечень для нового run, исходный запрос остаётся в истории.
При том же Idempotency-Key текст уточнения должен совпадать. Другой ключ во время
активного queued/running run — 409. Подтверждённое КП не обрабатывается заново.
Файл только сохраняется при import; worker извлекает текст после process.

Статусы run: queued, running, completed, needs_clarification, manual_review,
failed. У completed result содержит revision; у review — questions и нет новой
версии. При Redis 503 durable run уже сохранён: повторить тот же key или retry.
`retryable` у queued/failed и просроченного running помогает UI восстановить job.
Provider/model записаны при создании run. Смена конфигурации не меняет его задним числом.

OpenAPI: запустите `docker compose exec api python -c 'import json; from app.api import app; print(json.dumps(app.openapi(), ensure_ascii=False))'`.
