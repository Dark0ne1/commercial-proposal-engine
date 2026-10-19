# Модель данных

| Таблица | Назначение и ограничения |
|---|---|
| users | Email unique, PBKDF2-SHA256 hash с солью; роль менеджера |
| sessions | SHA256 от случайного токена, user FK, срок жизни |
| customers | Синтетические реквизиты, ставка и категория скидки (none/contract/partner/individual), оплата |
| products | Unique SKU, наименование, единица, Numeric цена/остаток, production/delivery/lead days |
| inquiries | UUID, customer FK, исходный текст, current/confirmed revision, create key и fingerprint, optimistic lock |
| quote_versions | UUID, inquiry FK, unique revision в заявке, JSON snapshot, unique key и fingerprint |
| audit_events | Inquiry FK, actor, action, JSON details, UTC timestamp |
| processing_runs | Inquiry FK, unique operation key + fingerprint, provider/model, immutable clarification, base revision, status, attempt, claim token/lease, extraction/result/error |
| agent_calls | Run FK, attempt, provider/tool kind, name, validated args, result/error, duration_ms, usage, timestamp |

Inquiry дополнительно хранит source_info (имя, тип, размер, SHA256, внутренний
путь исходного файла) и extracted_text. Путь не выдаётся в API.
История уточнений — отдельные ProcessingRun, исходный запрос не перезаписывается.
Снимок КП включает категорию скидки (manager_override при ручной смене ставки)
и отдельные сроки производства и доставки. lead_days — суммарный срок под заказ.
Старые записи мигрируются без изменения суммы срока: production=0, delivery=lead.

Все расчёты Decimal, в Numeric хранятся каталоговые деньги; в JSON денежные
значения — строки без float. Цены без НДС. По строке: round(qty × price, 2),
затем round(gross × discount / 100, 2). Сумма строк после скидки — net;
НДС = round(net × rate / 100, 2), ROUND_HALF_UP. Валюта первого этапа RUB.
Количество >0, не более 1 000 000, до 3 знаков. Цена >=0, до 2 знаков.
Наличие сравнивается с суммарным количеством SKU во всех строках КП.
Единица должна точно совпасть с каталогом. Скидка не выше MAX_DISCOUNT.
Налоги/скидки — демонстрационная конфигурация, не правовая настройка.

Данные seed воспроизводимы по фиксированному Random(20261019), стабильным
UUID и датам исторических КП. Пароль намеренно получает случайную соль,
времена событий записывают время импорта. Seed не обещает бинарно одинаковую БД.
Исторические КП: синтетические ручные разрешения исходных неоднозначностей.
Документы для них создаются кнопкой повторной генерации.

Сброс демобазы не удаляет файлы: они адресуются UUID версии. Для seed UUID
документа зависит от содержимого снимка: изменение supplier/tax не подхватит
старый файл. Старые неиспользуемые артефакты остаются в volume до очистки оператором.
