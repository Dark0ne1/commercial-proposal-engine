# Развёртывание Linux VPS

Нужны Docker Engine с Compose v2, 2 CPU/4 GB RAM как стартовый бюджет,
свободное место под PostgreSQL и документы. Ресурсный бюджет не нагрузочный тест.

1. Скопировать проект на сервер; создать `.env` из `.env.example`.
2. Задать разные длинные POSTGRES_PASSWORD и DEMO_PASSWORD. Для пароля БД
   используйте hex, например `openssl rand -hex 24`: он вставляется в URL.
3. Для локального демо оставить PUBLIC_ORIGIN=http://localhost:3000.
4. Выполнить `docker compose up -d --build`, затем `docker compose ps -a`.
   migrate должен завершиться с exit 0, api/web/db/redis/worker — healthy.
5. Выполнить `docker compose exec api python seed.py`.
6. Открыть http://localhost:3000, войти manager@example.test с DEMO_PASSWORD.
   На удалённом VPS можно использовать SSH tunnel:
   `ssh -L 3000:127.0.0.1:3000 user@server`.
7. Проверить `curl -f http://localhost:3000/api/health` и пройти сценарий КП.
   Ввести `SKU-0001, 2 шт.`, запустить разбор, дождаться черновика, подтвердить,
   скачать оба файла. Для импорта можно использовать `frontend/tests/fixtures/request.xlsx`.

Для публичного доступа настройте HTTPS reverse proxy к 127.0.0.1:3000,
PUBLIC_ORIGIN=https://your-domain, COOKIE_SECURE=true и rate limit login.
Пример ограничений Nginx в `docs/nginx.conf.example`; TLS сертификат выдаёт
оператор. Затем `docker compose up -d --force-recreate api web`.
Не публикуйте 5432/8000. Встроенного TLS и rate limit в приложении нет.

## Перезапуск и обновления

db/api/web/redis/worker имеют restart unless-stopped; данные в именованных volumes.
Redis использует AOF; исходные файлы и результаты — общий documents volume.
`docker compose restart` сохраняет данные и авторизацию до истечения сессий.
После обновления кода используйте `docker compose up -d --build` — миграции
выполняет единственный сервис migrate до API. Перед изменением схемы нужен backup.
`docker compose down` безопасен для volumes. `down -v` уничтожает их — для
обычного перезапуска не использовать. Worker выполняет Linux RQ fork workhorse,
healthcheck проверяет heartbeat worker этого контейнера (до 480 сек).
После аварии обработки дождитесь истечения lease (AGENT_TIMEOUT + 150 сек от
захвата) и нажмите повтор задачи. Уже созданный черновик повтор не дублирует.
Если Redis потерял job, сохранённый queued run можно повторно поставить в очередь.

## Провайдеры

`LLM_PROVIDER=mock` — режим по умолчанию, ключ и модель не требуются. Mock
распознаёт точные SKU или простые полные наименования с количеством/единицей;
при недостатке данных возвращает уточнение. Это детерминированная демонстрация,
не языковая модель.

Для OpenAI-compatible Chat Completions endpoint оператор задаёт
`LLM_PROVIDER=compatible`, `LLM_BASE_URL` (с /v1), `LLM_MODEL`, `LLM_API_KEY`.
Ключ хранить только в защищённом `.env`, не в Git или форме UI. Адаптер требует
tools/tool_calls, JSON object extraction и max_completion_tokens. Совместимость
конкретного провайдера проверять отдельно. После смены настроек пересоздать
`api worker`, а не продолжать старые runs с новым provider/model.
Вызовов внешнего провайдера в ходе разработки не было.

Лимиты: AGENT_MAX_STEPS=30, AGENT_TIMEOUT=120, LLM_TIMEOUT=20,
RENDER_TIMEOUT=90; backend Settings содержит допустимые диапазоны. RQ job timeout
равен AGENT_TIMEOUT + 120 сек; память worker ограничена 1 GB. RQ автоматически
повторяет ошибку до двух раз; дальше доступен ручной retry. В mock token usage
отсутствует; compatible сохраняет usage, когда его возвращает endpoint.

## Backup / restore

Проводить в период без изменений: `docker compose stop web api worker`.

```sh
mkdir -p backups
docker compose exec -T db pg_dump -U proposal -d proposal -Fc > backups/db.dump
docker compose run --rm -T --no-deps --user root --entrypoint tar api -C /app/storage -czf - . > backups/documents.tgz
docker compose start api worker web
```

Хранить оба файла защищённо вне VPS вместе с версией приложения и конфигом
(секреты отдельно). Для восстановления в отдельной чистой среде той же версии:

```sh
docker compose up -d db
docker compose exec -T db pg_restore -U proposal -d proposal --clean --if-exists < backups/db.dump
docker compose run --rm -T --no-deps --user root --entrypoint sh api -c 'cd /app/storage && tar xzf - && chown -R app:app /app/storage' < backups/documents.tgz
docker compose up -d
```

После восстановления БД можно использовать чистый Redis: очередь не источник
истины, незавершённые runs сохранены в PostgreSQL. После старта повторно поставить
их через UI; для running runs дождаться истечения lease. Не импортировать старую
очередь против другой версии БД. Для чистого перезапуска Redis с сохранением AOF
достаточно volumes; backup авторитетных данных — БД + documents.
Проверьте health, вход, старый DOCX/PDF и новую обработку после restore.
Рецепт восстановления здесь документирован; выполненный restore требует
отдельного инфраструктурного прогона, это не заявленная локальная проверка.

## Ошибки

`docker compose logs --tail=100 api worker migrate web db redis`. PDF 503: проверить
права volume, память, LibreOffice и лимит 90 сек; повторить документы.
Login 403: Origin должен совпадать с PUBLIC_ORIGIN включая порт. Для локального
HTTP разрешены оба адреса localhost и 127.0.0.1 с тем же портом; для публичного
домена действует точное совпадение.
После смены POSTGRES_PASSWORD в env пароль уже существующей БД автоматически
не меняется. Изменяйте роль отдельно с backup, не удаляйте volume.
Process 503: Redis/worker и их healthchecks; повторить задачу после восстановления.
LLM provider_http_401: конфигурация ключа; 429/5xx: ограниченные RQ retries.
provider_configuration_changed: создать новый run с актуальной конфигурацией.
Импорт формул/сканов/невалидных единиц требует исправления или ручного подбора.
