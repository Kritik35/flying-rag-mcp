# Handoff: 2026-06-20

Документ фиксирует состояние проекта после production-аудита, фиксов поиска,
live DB cleanup и обезличивания публичных файлов.

## Короткий статус

- Основная ветка: `master`.
- Последний подтвержденный и запушенный production-коммит: `f4c5ab4 fix: scope visual and table retrieval`.
- Для `f4c5ab4` unit/integration проверки и GitHub Actions были зелеными.
- Текущий redaction/anonymization-проход завершен на уровне fixtures/docs; перед публикацией нужен финальный full-test и отдельный коммит.
- Индекс, LanceDB и боевую vector DB в redaction-проходе не трогали.
- AI-bridge не использовать: `run_gemini`, `run_qwen`, `run_hermes`, `save_to_shared` запрещены по `AGENTS.md`.

## Что сделано

### Search/retrieval

В `f4c5ab4` уже сделано и запушено:

- `search_drawings` учитывает routing/scope и принимает `dataset`/`folder_filter`.
- `search_documents(include_visual=True)` фильтрует visual hits по примененному scope.
- Убран лишний повторный embedding на cache miss.
- `sum_table_values(dataset=...)` реально фильтрует по dataset.
- Стабилизирован порядок кандидатов табличного поиска.
- `save_engineering_rule` стал идемпотентным для точных дублей.
- Legacy smoke scripts пропускаются в `unittest discover`.
- Добавлены regression-тесты для visual scope, search efficiency, table dataset filtering и rules extractor config.

### Live DB cleanup

Перед чисткой созданы backup-файлы:

- `data/metadata_pre_cleanup_20260620_100504.db`
- `data/rules_backup_20260620_100504.db`

Сделано:

- удалена основная масса дублей `engineering_rules`;
- нормализованы несколько строк с битым `dataset`;
- подтверждено, что активный старый backfill может продолжать писать дубли, пока не остановлен/не перезапущен на свежем коде.

Осталось:

- финальный dedup делать только после остановки/завершения backfill или после его рестарта на новом коде;
- перед `apply=True` обязательно сделать backup и dry-run.

### Redaction/anonymization

Публичные файлы очищены от проектно-специфичных примеров:

- чувствительные термины заменены на нейтральный `Параметр настройки`;
- проектоподобные номера систем заменены на нейтральные regex-compatible placeholders;
- проектные имена файлов, реквизиты, адресные и организационные фрагменты заменены на нейтральные значения;
- тестовые fixtures сохранены рабочими: structured extractor по-прежнему проверяет реальные форматы записей, но без реальных идентификаторов.

Измененные файлы redaction-прохода:

- `README.md`
- `build_table_parquet.py`
- `config/retrieval_terms.yaml`
- `docs/RAG_NOREINDEX_PLAN.md`
- `docs/SESSION_HANDOFF_2026-06-20.md`
- `rag_server/query_router.py`
- `rag_server/tools.py`
- `test_mcp_structured_values.py`
- `test_query_router_scope.py`
- `test_retrieval_quality.py`
- `test_search_quality_integration.py`
- `test_structured_values.py`
- `test_table_query.py`

## Проверки redaction-прохода

Focused-набор после фикса placeholders зеленый:

```powershell
python -m unittest test_query_router_scope test_mcp_structured_values test_structured_values test_table_query test_retrieval_quality -v
```

Sensitive scan должен возвращать только ожидаемые false-positive технические слова в `parsers/office.py`
или совсем пустой результат:

```powershell
rg -n -i "<local-sensitive-pattern>" --glob "!data/**" --glob "!.git/**" --glob "!scratch/**" --glob "!**/__pycache__/**"
```

Финальные команды, пройденные перед коммитом:

```powershell
git diff --check
python -m unittest discover -v
FLYING_RAG_RUN_INTEGRATION=1 python -m unittest test_search_quality_integration -v
python -m py_compile rag_server/tools.py storage/vector_store.py rag_server/reranker.py rag_server/query_router.py rag_server/server.py
```

## Что осталось сделать

1. Дождаться/остановить текущий backfill и выполнить финальный dry-run/dedup `engineering_rules`.
2. Перезапустить MCP-процессы, чтобы Claude Desktop/Qwen Chat взяли свежий код.
3. Smoke-test MCP-инструменты:
   - `search_documents(debug=True)`;
   - `search_documents(include_visual=True)`;
   - `search_drawings(dataset=..., folder_filter=...)`;
   - `extract_structured_values`;
   - `sum_table_values(dataset=...)`.
4. После зеленого CI и финального ручного review можно решать вопрос перевода репозитория из private в public.

## Чего не делать

- Не публиковать репозиторий до зеленого CI после redaction-коммита.
- Не повторять в документах значения API keys или реальные строки из командных строк процессов.
- Не трогать live index/vector store ради redaction.
- Не делать destructive DB cleanup во время активной записи backfill.
- Не вызывать AI-bridge.

## Архитектурные хвосты

- Atomic rebuild/swap вместо прямого reset production DB.
- Отдельный offline rules backfill вместо per-chunk LLM в основном indexing pipeline.
- Решить судьбу `validator/crag.py`: подключить к reindex-tier или удалить как dead code.
- Расширить adversarial golden-set для retrieval quality.
- Уточнить release checklist для публичной публикации.
