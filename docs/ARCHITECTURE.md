# Архитектура

FastAPI API, Next.js UI, PostgreSQL, Redis/RQ worker и файловый volume.
UI использует same-origin `/api` через ограниченный Next route handler;
реальный адрес API задаёт серверная переменная API_INTERNAL_URL.
Бизнес-правила находятся в application/domain. ORM и Session служат
инфраструктурой без дополнительного абстрактного repository wrapper.
API проверяет вход, сессию и делегирует use case.

```mermaid
flowchart LR
  M[Менеджер] --> UI[Next.js / Tailwind]
  UI --> Proxy[Same-origin API proxy]
  Proxy --> API[FastAPI / Pydantic]
  API --> UC[Application use cases]
  UC --> D[Domain: Decimal / snapshots]
  UC --> ORM[SQLAlchemy 2]
  ORM --> PG[(PostgreSQL)]
  API --> Render[Document rendering]
  Render --> LO[python-docx / LibreOffice]
  LO --> V[(Documents volume)]
  Migration[Alembic migrate service] --> PG
  API --> Intake[Upload / provenance]
  Intake --> V
  UC --> Runs[(Durable processing runs)]
  Runs --> PG
  UC --> Queue[(Redis / RQ)]
  Queue --> Worker[RQ worker]
  Worker --> Extraction[DOCX / XLSX / PDF text extraction]
  V --> Extraction
  Worker --> Agent[Bounded agent loop]
  Agent --> LLM[Mock or OpenAI-compatible provider]
  Agent --> Tools[Six Pydantic tools]
  Tools --> UC
```

```mermaid
sequenceDiagram
  actor Manager as Менеджер
  participant UI as Next.js
  participant API as API / Application
  participant DB as PostgreSQL
  participant RQ as Redis / RQ
  participant Worker as Worker / Agent
  participant LLM as Mock or compatible API
  participant DOC as Document renderer
  Manager->>UI: Клиент и текст обращения
  UI->>API: POST inquiries + Idempotency-Key
  API->>DB: Заявка + audit, commit
  Manager->>UI: Разобрать заявку
  UI->>API: POST process + Idempotency-Key
  API->>DB: Durable ProcessingRun, commit
  API->>RQ: Enqueue fixed function / run UUID
  RQ->>Worker: Claim run with expiring lease
  Worker->>DB: Read source / extract file text
  Worker->>LLM: Extract structured request
  loop Limited steps / timeout
    LLM->>Worker: Typed tool call
    Worker->>DB: Validate / read verified facts / log duration
    Worker->>LLM: Tool result with tool_call_id
  end
  alt Missing or ambiguous data
    Worker->>DB: Questions / manual_review, no quote
    Manager->>API: Full clarified list, new processing run
  else Unique match and valid quantities
    Worker->>DB: Snapshot draft + history, no approval
  end
  Manager->>UI: Каталог, количество, цены, условия
  UI->>API: POST versions + expected_revision + key
  API->>DB: SELECT FOR UPDATE заявки
  API->>API: Validate + Decimal calculation
  API->>DB: Immutable snapshot + audit, commit
  Manager->>UI: Подтвердить текущую версию
  UI->>API: POST confirm revision
  API->>DB: Lock, freeze version, audit, commit
  API->>DOC: DOCX + isolated LibreOffice profile → PDF
  alt Ошибка конвертации
    API->>DB: documents.failed
    API-->>UI: 503, повторная генерация допустима
  else Успех
    DOC-->>API: Atomic files replacement
    API->>DB: documents.generated + duration
    API-->>UI: URLs защищённых файлов
  end
  Manager->>API: Скачать файл (проверка сессии)
```

Каждый черновик — новая QuoteVersion. Снимок включает реквизиты обеих сторон,
товары, каталоговую и выбранную цены, остатки, сроки, скидку, НДС, итоги,
оплату, дату и срок действия, комментарий. Изменение каталога, клиента или
конфига не меняет старое КП. История не выполняет live join для документов.

Конкуренция: PostgreSQL row lock на заявке, optimistic lock_version SQLAlchemy,
unique operation keys и (inquiry_id, revision), expected_revision от клиента.
Второй конкурентный запрос получает тот же результат после повтора либо 409.
Повтор подтверждения не дублирует событие. Генерация использует lock заявки,
проверяет существующую пару файлов и отдельный профиль LibreOffice.

Сбой между записью файлов и audit может оставить готовые файлы без generated
события; операция безопасно повторяется, но это не distributed transaction.
Восстановление документов — повторная генерация из снимка. Остатки справочные,
резервирование и списание не выполняются.

Tools: get_customer (клиент привязан к заявке), search_catalog (индекс извлечённой
строки), get_price/check_availability (только однозначно найденный product_id),
calculate_quote/create_quote_draft (без аргументов денег/скидок/условий).
Количество, единица и source spans сверяются с исходным текстом; упомянутые
SKU нельзя молча опустить. Техническое наименование берётся из каталога.
Условия запроса хранятся отдельно, не становятся обещаниями поставщика.

Провайдеры: mock выполняет детерминированный разбор и выдаёт tool calls;
compatible использует Chat Completions tool protocol, JSON extraction и
Pydantic validation. Free text модели не попадает в коммерческий документ.
По умолчанию 30 tool calls, 120 секунд агента, 20 секунд HTTP call, 4000 output
tokens. После полного цикла принимается только валидный final status=done.

ProcessingRun сохраняется до enqueue. Недоступный Redis не теряет заявку:
повтор с тем же ключом или retry ставит тот же run в очередь. JSONSerializer
используется и enqueue, и worker. По умолчанию RQ делает до двух повторов
ошибки. SQL CAS захватывает lease, tools проверяют claim token под row lock.
Старый worker после потери lease не может создать КП или перезаписать новый claim.
Если worker погиб после commit черновика, повтор находит QuoteVersion по
agent-run UUID и завершает run без дублирования. После аварии и истечения lease
можно повторить задачу; бесконечного неявного повторения нет.

Исходный файл хранится content-addressed в incoming/ volume, digest и имя — в
БД. Извлечённый текст сохраняется отдельно от исходного обращения. PDF сканы
без текста не распознаются: OCR не входит в текущую реализацию.
