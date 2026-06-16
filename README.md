# Flying RAG MCP

Локальный MCP-сервер для RAG-поиска по инженерной документации: ГОСТ, СП,
проектные PDF/DOCX/XLSX, таблицы, текстовые файлы и BIM-форматы (IFC, DWG).
Полностью локальный стек: embeddings через [Lemonade](https://lemonade-server.ai)
(GPU/NPU), векторы в LanceDB, метаданные в SQLite. Рассчитан на Windows.

## Возможности

- **Гибридный поиск** — vector ANN + FTS/BM25 с настраиваемым весом `alpha`
- **Parent-child chunking** — child 150 ток. (retrieval) / parent 1000 ток. (контекст)
- **Фоновая индексация** watched-папок (watchdog) + ночной планировщик
- **Граф связей документов** — семантические соседи по центроидам
- **Семантический кэш** запросов (SQLite + cosine)
- **Термоконтроль** — динамическое троттлирование индексации по температуре/CPU
- **Извлечение инженерных правил** (опционально) — структурированные нормы
  (параметр/оператор/значение/единица) через локальный LLM
- Парсеры: PDF (+OCR опц.), DOCX (таблицы с gridSpan/vMerge), XLSX (формулы),
  TXT/CSV/JSON, IFC, DWG (через ODA Converter)

## Быстрый старт

1. **Python 3.12+** и зависимости:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements.txt
   ```
2. **Lemonade server** с моделью `Qwen3-Embedding-0.6B-GGUF` (dim=1024),
   чекбокс Embeddings включён.
3. **Конфигурация:**
   ```powershell
   copy config.example.yaml config.yaml
   # поправьте watched_folders и lemonade.base_url под свою машину
   ```
4. **Индексация:**
   ```powershell
   .\.venv\Scripts\python.exe reindex_all.py
   ```
5. **Подключение к Claude Desktop** — см. `claude_desktop_config.json`.
   Для Qwen Chat (uvx): `uvx --from fastmcp --with-requirements requirements.txt python main.py`

## Запуск MCP-сервера

```powershell
python main.py            # stdio MCP + watchdog мониторинг
python main.py --daemon   # фоновый режим с лог-ротацией
```

## Полный reindex

```powershell
.\.venv\Scripts\python.exe reindex_all.py --reset-store --force --no-cache
```

- `--reset-store` — удалить `data/lancedb` и `data/metadata.db`
- `--force` — игнорировать SHA-skip неизменённых файлов
- `--no-cache` — пересчитать все векторы заново

> ⚠️ Закрытие консоли убивает индексацию (exit 0x40010004).
> Для многодневных прогонов используйте Планировщик задач Windows —
> готовый лаунчер: `run_reindex_task.bat` (лог в `storage/reindex_release.log`).

## MCP tools

| Tool | Назначение |
|------|-----------|
| `search_documents(query, folder_filter?, top_k?, dataset?, rerank?, alpha?, use_cache?, debug?)` | гибридный поиск с авто-определением scope |
| `search_rules(query, subject?, parameter?, limit?)` | поиск по извлечённым правилам |
| `extract_structured_values(label, source_like?, limit?, max_rows?)` | эвристическое извлечение пар `система/объект → параметр → значение` из parent chunks |
| `list_indexed(folder_filter?, limit?, dataset?)` | файлы в базе |
| `graph_neighbors(doc_id, top_k?)` | связанные документы |
| `reindex_path(path, force?, use_cache?)` | индексация в фоне |
| `reindex_status(job_id?, limit?)` | статус задач |

## Авто-определение scope (deterministic routing)

`search_documents` прогоняет запрос через лёгкий детерминированный роутер
(`rag_server/query_router.py`, конфиг `config/retrieval_terms.yaml`, без LLM):

- по доменным терминам/паттернам выводит `dataset` и `folder_filter`
  (например, «противодымная вентиляция ОВ2» → `dataset=project`, `folder_filter=ОВ2`,
  и запрос больше не утекает в нормативку/ЭОМ);
- **явные `dataset`/`folder_filter` всегда имеют приоритет** и не переопределяются;
- конфликт нормативки и проекта (например, «ОВ2 + СП 7.13130») помечается как
  `ambiguous` — ни одна сторона не выбрасывается и агрессивный фильтр не применяется;
- при слабой выдаче делается один детерминированный weak-retry (без LLM);
- для табличных запросов («дорегулирование», «потеря давления») router возвращает
  hint на `extract_structured_values`.

`debug=true` возвращает объект `{"debug": {...trace...}, "results": [...]}` с
маршрутом, причиной, inferred/applied scope, ambiguous, subqueries, weak_retry и
structured hint. При `debug=false` (по умолчанию) формат прежний — список результатов.

## Извлечение правил (опционально)

`search_rules` требует наполнения: установите `langextract[openai]`,
включите `rules_extraction.enabled: true` в config.yaml и укажите
OpenAI-совместимый endpoint (локальный lemonade LLM или облачный ключ
через переменную окружения `OPENROUTER_API_KEY` / файл `.env`).

> Экстракция — по одному LLM-вызову на чанк. На большом корпусе включайте
> её отдельным проходом после векторизации, не в основном reindex.

## Тесты

```powershell
python -m unittest test_parent_child_pipeline.py test_production_readiness.py -v
```

Comprehensive suite (`python test_comprehensive.py`) запускать только когда
reindex не пишет в базу.

Fresh live retrieval smoke без semantic cache:

```powershell
$env:FLYING_RAG_RUN_INTEGRATION='1'
python -m unittest test_search_quality_integration.py -v
```

## Структурное извлечение параметров

Для задач вида «найди значение параметра по техлистам/таблицам», где обычный
RAG теряет связь между системой, заголовком и числом, используйте отдельный
эвристический extractor по уже проиндексированным `parent_chunks`:

Через MCP:

```json
{
  "label": "Потеря давления",
  "source_like": "ОВ2",
  "limit": 500,
  "max_rows": 50
}
```

Через CLI:

```powershell
python scripts\extract_structured_values.py --label "Дорегулирование" --source-like "ОВ2" --name doregulirovanie
python scripts\extract_structured_values.py --label "Потеря давления" --source-like "ОВ2" --name pressure_loss
```

Результаты пишутся в `scratch/structured_values/` и не попадают в Git.
Критичные строки нужно сверять с исходными PDF/XLSX: extractor восстанавливает
связи эвристически, а не заменяет табличный парсер исходного формата.

## Обслуживание правил

До завершения backfill правил выполнять только dry-run:

```powershell
python scripts\dedup_engineering_rules.py
```

После завершения backfill и проверки отчёта можно удалить точные дубли:

```powershell
python scripts\dedup_engineering_rules.py --apply
```

## Структура

```
main.py            — точка входа MCP (stdio) + watchdog
indexer.py         — индексация файла/папки (subprocess-друг)
reindex_all.py     — полный прогон по watched_folders
rag_server/        — MCP-сервер и инструменты
chunker/           — parent-child + табличные чанкеры
parsers/           — PDF/DOCX/XLSX/IFC/DWG/текст
embedder/          — lemonade-клиент, батчер, термоконтроль
storage/           — LanceDB, SQLite, граф, кэш, правила
data/, storage/*.log — runtime-артефакты (gitignored)
```

## Лицензия

MIT — см. [LICENSE](LICENSE).
