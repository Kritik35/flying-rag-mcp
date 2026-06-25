# Flying RAG MCP

Локальный MCP-сервер для инженерного RAG-поиска по нормативной и проектной
документации: PDF/DOCX/XLSX, таблицы, текстовые файлы, IFC/DWG и чертежи.
Стек рассчитан на локальную Windows-машину: embeddings через OpenAI-compatible
Lemonade, векторное хранилище LanceDB, метаданные SQLite, MCP-инструменты для
Claude Desktop, Qwen Chat и других клиентов.

## Текущее состояние

Актуально на 2026-06-25.

- Основная ветка: `master`.
- Embeddings: `Qwen3-Embedding-0.6B-GGUF`, размерность 1024.
- OpenAI-compatible endpoint по умолчанию: `http://localhost:13305/api/v1`.
- Parent-child chunking: parent 1000 токенов, child 150 токенов.
- Гибридный поиск: vector + FTS/BM25, стандартный `alpha=0.7`.
- PDF-маршрут: `parsers.pdf_vision`.
- Сканированные PDF: сначала Vision/LLM OCR, затем локальный OCR fallback.
- Локальный OCR: Tesseract через `PATH`, `TESSERACT_CMD` или стандартные
  `Program Files` пути; персональные пути в коде не используются.
- Backfill правил поддерживает безопасную передачу ключа через переменную
  окружения или файл, без публикации ключа в CLI/history.

## Возможности

- `search_documents` — гибридный поиск с auto-routing, debug trace,
  optional rerank и optional visual results.
- `search_drawings` — визуальный поиск по страницам чертежей.
- `sum_table_values` — детерминированное суммирование/подсчет числовых колонок
  из таблиц через повторный парсинг исходного файла.
- `extract_structured_values` — извлечение label/value пар из parent chunks.
- `search_rules` — поиск по извлеченным инженерным правилам.
- `list_indexed`, `graph_neighbors`, `reindex_path`, `reindex_status` —
  обслуживание корпуса и графа документов.

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy config.example.yaml config.yaml
```

После копирования настройте локальный `config.yaml`: watched folders, endpoint
Lemonade, модели и правила индексации. `config.yaml`, runtime-базы, логи и
scratch-артефакты исключены из Git.

Запуск MCP:

```powershell
python main.py
```

Полная индексация:

```powershell
.\.venv\Scripts\python.exe reindex_all.py --reset-store --force --no-cache
```

Для длинных прогонов не закрывайте консоль: на Windows это может оборвать
индексацию. Надежнее запускать многодневные задачи через Планировщик задач или
другой внешний supervisor.

## OCR и PDF

PDF обрабатываются через guarded pipeline:

1. PyMuPDF извлекает текстовый слой.
2. Таблицы и страницы проверяются через существующие парсеры.
3. Если текстового слоя нет, вызывается Vision/LLM OCR.
4. Если Vision недоступен или вернул пустой результат, включается локальный OCR.

Для Tesseract достаточно одного из вариантов:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
python main.py
```

или добавить `tesseract.exe` в `PATH`. Если исполняемый файл не найден, OCR
provider остается `none`, а MCP не падает.

## Backfill правил

Безопасные варианты передачи ключа:

```powershell
python backfill_rules.py --api-key-env OPENROUTER_API_KEY
python backfill_rules.py --api-key-file .\secrets\openrouter.key
```

`--api-key` оставлен только для совместимости и не рекомендуется: значение
может попасть в историю shell или список процессов.

## MCP tools

| Tool | Назначение |
| --- | --- |
| `search_documents(query, folder_filter?, top_k?, dataset?, rerank?, alpha?, use_cache?, debug?, include_visual?)` | Гибридный поиск по документам |
| `search_drawings(query, dataset?, folder_filter?, top_k?)` | Визуальный поиск по чертежам |
| `sum_table_values(subject, field?, op?, source_like?, dataset?)` | Проверяемая сумма/количество по таблицам |
| `extract_structured_values(label, source_like?, limit?, max_rows?)` | Извлечение структурированных значений |
| `search_rules(query, subject?, parameter?, limit?)` | Поиск инженерных правил |
| `list_indexed(folder_filter?, limit?, dataset?)` | Список файлов в индексе |
| `graph_neighbors(doc_id, top_k?)` | Семантические соседи документа |
| `reindex_path(path, force?, use_cache?)` | Фоновая переиндексация файла или папки |
| `reindex_status(job_id?, limit?)` | Статус задач индексации |

## Проверки

Фокусный набор перед публикацией текущего состояния:

```powershell
python -m py_compile parsers\ocr.py parsers\pdf.py parsers\pdf_vision.py parsers\dispatcher.py backfill_rules.py test_backfill_rules_config.py test_config_example.py test_pdf_ocr_pipeline.py
python -m unittest test_backfill_rules_config.py test_config_example.py test_pdf_ocr_pipeline.py test_mcp_structured_values.py test_parent_child_pipeline.py test_production_readiness.py test_query_planner.py test_rerank_policy.py test_retrieval_quality.py test_rules_maintenance.py test_structured_values.py test_vector_store_context.py -v
```

Интеграционный smoke по живому индексу запускайте отдельно, только когда
индексация не пишет в runtime-базы:

```powershell
$env:FLYING_RAG_RUN_INTEGRATION = "1"
python -m unittest test_search_quality_integration.py -v
```

## Privacy

В Git не должны попадать:

- `config.yaml`, `.env`, ключи API и реальные CLI-команды с ключами;
- `data/`, LanceDB, SQLite runtime-базы, backup DB и логи;
- локальные рабочие папки с входными документами;
- персональные абсолютные пути и имена пользователей;
- результаты анализа, scratch-таблицы и временные файлы агентов.

Перед коммитом полезно запускать targeted scan по staged diff и публичным
файлам. Локальные инструкции агентов (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`,
`QWEN.md`) намеренно не публикуются.

## Структура

```text
main.py             MCP entrypoint + watchdog
indexer.py          индексатор файла или папки
reindex_all.py      полный проход по watched folders
rag_server/         MCP tools, routing, retrieval, rerank
chunker/            parent-child и табличное разбиение
parsers/            PDF/DOCX/XLSX/IFC/DWG/text/OCR
embedder/           Lemonade client, batching, thermal control
storage/            LanceDB, SQLite, graph, cache, rules
docs/               публичные handoff и roadmap документы
```

## Лицензия

MIT, см. [LICENSE](LICENSE).
