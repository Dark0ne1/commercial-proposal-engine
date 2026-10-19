# Тестирование

## Backend

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
ruff check .
ruff format --check .
pytest -q
```

По умолчанию тесты используют disposable SQLite in-memory и dependency override
Session. Это проверяет домен/API, но не PostgreSQL row locks. Для реальной
конвертации установите LibreOffice и fonts-dejavu (`LIBREOFFICE_BIN` при необходимости).
Без LibreOffice document/PDF integration tests будут skipped.

PostgreSQL прогон: задайте `TEST_DATABASE_URL=postgresql+psycopg://.../proposal_test`.
**Тесты удаляют и создают все таблицы этой БД. Только отдельная test database.**
GitHub Actions использует отдельный PostgreSQL service, проверяет миграции,
выполняет pytest с LibreOffice, Ruff, UI build/typecheck и npm audit.
Сквозной Compose job поднимает реальные контейнеры, делает seed и browser e2e.
Добавленная CI-конфигурация не означает выполненный CI: нужен запуск в GitHub.

Покрытие: 10 эталонных денежных расчётов, auth/Origin, поиск и неоднозначность,
неверные количества/единицы, seed и повторы, версии и ручные цены, snapshot
после изменения каталога, stale revision, повтор подтверждения, реальные DOCX/PDF
и кириллица, ошибки и timeout конвертера. Дополнительно: 16 эталонных агентных
сценариев в `backend/tests/agent_golden.json`, typed tool validation, запрет
выдуманных цен/SQL/пропущенных SKU, provider 401/429/500/timeout/invalid schema,
настоящий Chat Completions tool message protocol с локальным MockTransport,
token usage, wall clock/step limits, RQ повтор после 429, lease fencing,
восстановление уже созданного черновика. Внешние LLM API не вызываются.
Очередь в тестах — настоящий RQ с fakeredis, не замена production Redis.
Import tests покрывают DOCX/XLSX/текстовый PDF, сканы, формулы, ZIP bombs/DTD,
SHA256, ложные XLSX dimensions и неправильный формат.

## UI и browser

```sh
cd frontend
npm ci
npm run typecheck
npm run build
# При работающих API/UI и seed; пароль как при seed:
DEMO_PASSWORD=your-password npm run test:e2e
```

Тест использует установленный Chrome (`channel=chrome`). В Linux CI Chrome
устанавливает Playwright. Он проходит login → заявка → товар → расчёт → правка
→ новая версия → подтверждение → download PDF/DOCX → журнал, сохраняет desktop
и mobile screenshots. API не подменяется. Для другого адреса задайте E2E_URL.
Есть также XLSX → RQ → агент → подтверждение → документы и неоднозначный
запрос → уточнение → черновик. Для этих тестов нужен работающий worker/Redis.
Тесты создают демозаявки и не удаляют их.

## Локальный запуск без Docker (только разработка)

Из backend, с активным venv, `DATABASE_URL=sqlite:///../local.db alembic upgrade head`,
затем с тем же DATABASE_URL и DEMO_PASSWORD запустить `python seed.py` и
`uvicorn app.api:app --host 127.0.0.1 --port 8000`.
В frontend `npm run dev`. SQLite — только удобство разработки; PostgreSQL
остаётся целевой БД. Для browser URL 127.0.0.1 задайте
`PUBLIC_ORIGIN=http://127.0.0.1:3000`; не смешивайте localhost и 127.0.0.1.

Для агента предпочтителен настоящий Redis. В Windows QA без Docker есть явно
тестовый `backend/local_queue.py`: он запускает эфемерный Redis TCP emulator
на 127.0.0.1:16379 и RQ SimpleWorker с TimerDeathPenalty. API задайте
`REDIS_URL=redis://127.0.0.1:16379/0?protocol=3`; helper и API должны использовать одинаковые
DATABASE_URL и STORAGE_DIR. При остановке эмулятора данные очереди теряются,
заявки/processing runs остаются в БД. Это не проверка реального Redis.
В production использовать только `worker.py` и Redis из Compose.

Фактически выполненные команды и ограничения: [VERIFICATION.md](VERIFICATION.md).
