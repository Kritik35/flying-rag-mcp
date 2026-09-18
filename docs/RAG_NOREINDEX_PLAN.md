# No-Reindex Roadmap

Этот документ фиксирует улучшения, которые дают эффект без полного
переэмбеддинга корпуса. Актуально на 2026-09-17.

## Приоритеты после аудита 2026-09-17

Подробные доказательства, ограничения и критерии приёмки:
[GEMINI_REVIEW_2026-09-17.md](GEMINI_REVIEW_2026-09-17.md).
Этот раздел имеет приоритет над историческими статусами ниже.

1. P1: честная полнота агрегатов, единицы, запрет смены явно выбранного поля.
2. P1: идентичность документов между папками, актуальность и атомарная запись
   Parquet, общий config resolver для табличного пути.
3. P2: границы/короткие идентификаторы и paginated exact-occurrences MCP.
4. P2: выбор таблицы, provenance, пагинация и перенос шапок между страницами.
5. P2: расширение существующего regex-экстрактора и размеченная оценка качества.

Parquet, lexical boost и локальное извлечение уже подключены. Повторно внедрять
их с нуля не требуется. Проценты автоматизации из внешнего отчёта не доказаны.
Эти пункты открыты; в данном проходе обновлены документы, код не исправлялся.
Полный переэмбеддинг не нужен; обновление табличного кеша согласуется отдельно.

## Статус

Основные механизмы no-reindex трека реализованы: retrieval routing, rerank
policy, CRAG-style weak retry, structured extraction и проверяемые табличные
суммы уже работают поверх существующего индекса. Текущий фокус смещен на
качество парсеров, OCR fallback, безопасный backfill правил и тестовую защиту.

## Сделано

| Направление | Статус |
| --- | --- |
| Native rerank endpoint через Lemonade-compatible config | Сделано |
| Eval harness: Hit@k, MRR, Precision@k | Сделано |
| CRAG-style grading и weak retry только при слабой выдаче | Сделано |
| Auto-routing по dataset/folder для проектных и нормативных запросов | Сделано |
| `extract_structured_values` для label/value пар | Сделано |
| `sum_table_values` с детерминированным пересчетом исходных таблиц | Сделано |
| Visual scope для `search_drawings` и `include_visual` | Сделано |
| PDF guarded pipeline с локальным OCR fallback | Сделано 2026-06-25 |
| Безопасная передача ключа в `backfill_rules.py` | Сделано 2026-06-25 |

## Обновление 2026-08-30 — контракты и честный трейс

По итогам разбора LES (см. [LES_RESEARCH_2026-08-30.md](LES_RESEARCH_2026-08-30.md))
закрыт класс тихих отказов. Все четыре пункта — без переиндексации.

| Направление | Статус |
| --- | --- |
| Контракт эмбеддингов: сверка модели сервера с моделью индекса | Сделано |
| `index_manifest.json` рядом с LanceDB (модель, размерность, чанкер) | Сделано |
| Честный retrieval trace: channels/fusion/score_kind/status | Сделано |
| Контракт реранка: pool/candidate_limit/input/returned/head_changed | Сделано |
| OCR fail-closed: коды ошибок вместо строк-заглушек в индексе | Сделано |
| Per-page маршрутизация OCR вместо решения по документу целиком | Сделано |
| Статус файла `indexed_partial_ocr` / `indexed_ocr_failed` | Сделано |
| Путь к `metadata.db` резолвится от корня репозитория, не от CWD | Сделано |
| Статистика parent hydration в трейсе | Сделано |
| Сквозной offline-гейт `test_e2e_contracts.py` (стаб-эмбеддер) | Сделано |
| Харнесс замера `scripts/rag_eval.py` + [EVAL_RUNBOOK](EVAL_RUNBOOK.md) | Сделано |
| Единый резолвер конфига + `FLYING_RAG_CONFIG` | Сделано |
| Одна команда локальной проверки `scripts/verify_local.py` | Сделано |

Отдельная находка, всплывшая только на сквозном прогоне: `_get_sqlite_path()`
возвращал путь относительно **текущей директории**. MCP-сервер запускается
клиентом с произвольным CWD, поэтому `metadata.db` не находился, `parent_chunks`
молча не подтягивались и каждый результат отдавал child-чанк на 150 токенов
вместо parent-контекста на 1000. Ошибки в лог не шло, выдача выглядела
правдоподобно. Путь теперь резолвится от корня репозитория, авторитетный путь
приходит от вызывающего кода, а факт отката на child виден в
`retrieval.parent_hydration`.

Ключевое: размерность вектора не является идентичностью модели. Qwen3-Embedding-0.6B
и bge-m3 оба дают 1024, а таблица называлась `documents_{dim}` — расхождение моделей
было принципиально ненаблюдаемым. Теперь несовпадение блокирует поиск с
`error_code=embedding_contract_mismatch` и явным действием оператора.

Гибрид, упавший в vector-only, больше не выдаёт себя за гибрид: `status=degraded`,
`fusion=none`, `channels=["dense"]` в debug-трейсе.

## Обновление 2026-06-25

Проверка после внешних изменений показала риск регрессии PDF/OCR: PDF должен
оставаться на guarded `parsers.pdf_vision`, а не уходить на упрощенный парсер.
Для этого добавлены regression-тесты:

- dispatcher для `.pdf` возвращает `parsers.pdf_vision`;
- raster PDF при пустом Vision OCR использует локальный OCR fallback;
- Tesseract provider не активируется, если исполняемый файл не найден;
- Tesseract можно настроить через нейтральный `TESSERACT_CMD`.

Эти изменения не требуют переиндексации уже существующего корпуса. Они влияют
на новые или повторно обработанные PDF, а также на надежность будущих reindex и
backfill прогонов.

## Что не трогать без отдельного решения

- Полный переэмбеддинг корпуса.
- Runtime LanceDB и `metadata.db` ради документации или redaction.
- Destructive dedup/cleanup `engineering_rules`, пока backfill может писать в
  базу.
- AI-bridge делегирование внешним агентам из этого репозитория.

## Следующие no-reindex шаги

1. Расширить golden-set трудными adversarial запросами, где baseline реально
   ошибается.
2. Добавить live smoke для сканированного PDF fixture, если появится
   обезличенный публичный пример.
3. Уточнить судьбу indexing-time `validator/crag.py`: подключать при следующем
   reindex-tier проходе или удалить как dead code.
4. После завершения backfill выполнить dry-run dedup `engineering_rules`, затем
   apply только с backup.

## Reindex-tier идеи

Эти пункты потенциально полезны, но требуют отдельного окна, compute budget и
явного согласования:

- contextual retrieval с локальным LLM;
- late chunking;
- более тяжелый embedder;
- отдельный ColPali/multivector pipeline для чертежей.

## Проверки для этого трека

```powershell
python -m unittest tests.test_backfill_rules_config tests.test_config_example tests.test_pdf_ocr_pipeline tests.test_mcp_structured_values tests.test_parent_child_pipeline tests.test_production_readiness tests.test_query_planner tests.test_rerank_policy tests.test_retrieval_quality tests.test_rules_maintenance tests.test_structured_values tests.test_vector_store_context -v
```

Интеграционные тесты с живым индексом запускать отдельно и только когда нет
параллельной записи в runtime-базы.
