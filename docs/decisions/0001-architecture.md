# ADR 0001: модульный монолит и неизменяемые версии

Статус: принято, расширено агентным этапом.

Контекст: нужен воспроизводимый путь от заявки до проверяемых документов,
который доступен AI через явные инструменты.

Решение: FastAPI + SQLAlchemy/PostgreSQL, Next.js UI, Decimal domain,
application use cases, Alembic migration job. JSON snapshot версии содержит
все коммерческие данные. Documents строятся только из подтверждённого snapshot.
Одна DB transaction на сценарий, row/optimistic locks и unique idempotency keys.
Подтверждение коммитится до рендера, рендер можно повторить после сбоя.

Последствия: небольшой deploy footprint, бизнес-функции пригодны для tools без
дублирования. Синхронный LibreOffice занимает HTTP/thread/DB connection до 90 сек;
при росте нагрузки его можно вынести в RQ. Текущий worker обрабатывает входящие
документы и агентный цикл. Файлы, Redis и БД не одна транзакция: durable runs,
повтор enqueue и стабильный agent operation key обеспечивают восстановление.
SQL lease/CAS с fencing не позволяет старому worker писать после нового claim.
Mock и compatible используют общий typed registry, модель не задаёт деньги.
SQLite применяется только для локальных быстрых тестов, не заменяет проверку
PostgreSQL locks и реальный Compose smoke.
