# No-Reindex Roadmap

Этот документ фиксирует улучшения, которые дают эффект без полного
переэмбеддинга корпуса. Актуально на 2026-06-25.

## Статус

Высокоэффективная часть no-reindex трека закрыта: retrieval routing, rerank
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
python -m unittest test_backfill_rules_config.py test_config_example.py test_pdf_ocr_pipeline.py test_mcp_structured_values.py test_parent_child_pipeline.py test_production_readiness.py test_query_planner.py test_rerank_policy.py test_retrieval_quality.py test_rules_maintenance.py test_structured_values.py test_vector_store_context.py -v
```

Интеграционные тесты с живым индексом запускать отдельно и только когда нет
параллельной записи в runtime-базы.
