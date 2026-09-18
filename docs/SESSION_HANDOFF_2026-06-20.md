# Handoff: обновление 2026-09-17

Актуальный аудит и список release gates:
[GEMINI_REVIEW_2026-09-17.md](GEMINI_REVIEW_2026-09-17.md).

- Проверены аналитический скрипт Gemini, агрегаты и реализация MCP.
- Подтверждено: regex extraction, Parquet-first и lexical boost уже работают
  как кодовые пути. Оценка экономии 75–80% не доказана.
- Воспроизведены смена явно выбранного поля суммы, потеря одноимённых файлов
  из разных папок, пропуск коротких шифров и ложное exact-совпадение по префиксу.
- 142 теста: 0 ошибок, 1 skipped; базовый py_compile успешен.
- Кодовые исправления, live MCP smoke, cleanup, commit/push не выполнялись.
  Runtime проверен read-only. Текущий CI не проверялся.
- Рабочее дерево содержит ранее внесённые правки, включая staged перенос
  тестов в `tests/`. Продолжать с их учётом; документация этого аудита не staged.

Следующий шаг: regression-тесты и исправления P1 табличной достоверности из
roadmap. Новые обещания production readiness до закрытия gates не давать.

## Историческая запись 2026-06-25

Документ обновляет состояние репозитория после ревью, исправления OCR-regression
риска, обновления публичных Markdown и подготовки к публикации в GitHub.

## Короткий статус

- Основная ветка: `master`.
- Runtime-индекс, LanceDB и рабочие SQLite-базы в этом проходе не изменялись.
- Публичные Markdown обновлены: `README.md`, `docs/RAG_NOREINDEX_PLAN.md`,
  `docs/SESSION_HANDOFF_2026-06-20.md`.
- Локальные агентские файлы и рабочие папки с входными данными не добавлялись в
  Git.
- MCP/DB могут параллельно читаться другими клиентами; destructive операции с
  базой не выполнялись.

## Что проверено ревью

1. Внешние изменения по `backfill_rules.py`, `config.example.yaml`,
   `parsers/ocr.py`, `parsers/pdf_vision.py` и CI.
2. Новый OCR path: PDF dispatcher, Vision OCR, локальный Tesseract fallback.
3. Безопасность передачи API key для rules backfill.
4. Публичные документы на предмет устаревшего статуса и приватных данных.
5. Git hygiene: untracked local artifacts не должны уйти в commit.

## Найдено и исправлено

### PDF/OCR

Риск: PDF-маршрут мог быть упрощен так, что guarded `pdf_vision` pipeline не
использовался бы для сканированных PDF. Это закрыто regression-тестом:
dispatcher для `.pdf` обязан возвращать `parsers.pdf_vision`.

Риск: при пустом Vision OCR не было достаточно защищенного локального fallback.
Добавлен fallback через `OCRParser`, а тест проверяет, что raster PDF получает
текст из локального OCR и помечает метод как `ocr_tesseract`.

Риск: Tesseract provider мог считаться доступным только по наличию Python
пакета. Теперь provider включается только когда найден реальный исполняемый
файл.

### Privacy

Риск: в коде был персональный Windows-путь к Tesseract внутри профиля
пользователя. Он удален. Поддерживаемые способы:

- `TESSERACT_CMD`;
- `PATH`;
- стандартные `Program Files` пути.

### Backfill

`backfill_rules.py` принимает ключ через:

- `--api-key-env`;
- `--api-key-file`;
- legacy `--api-key` только для совместимости.

Рекомендованный режим — env/file, чтобы ключ не попадал в history и process
arguments.

## Проверки

Фокусная OCR-проверка:

```powershell
python -m unittest test_pdf_ocr_pipeline.py -v
```

Расширенный набор:

```powershell
python -m py_compile parsers\ocr.py parsers\pdf.py parsers\pdf_vision.py parsers\dispatcher.py backfill_rules.py test_backfill_rules_config.py test_config_example.py test_pdf_ocr_pipeline.py
python -m unittest test_backfill_rules_config.py test_config_example.py test_pdf_ocr_pipeline.py test_mcp_structured_values.py test_parent_child_pipeline.py test_production_readiness.py test_query_planner.py test_rerank_policy.py test_retrieval_quality.py test_rules_maintenance.py test_structured_values.py test_vector_store_context.py -v
```

Перед публикацией также нужен staged privacy scan по абсолютным путям, API-key
паттернам, runtime DB/log именам и локальным рабочим папкам.

## Не включать в Git

- `config.yaml`, `.env`, API keys.
- `data/`, `storage/lancedb/`, runtime SQLite DB и backup DB.
- `.codex_mtr_work/`, `input/`, scratch/results.
- Локальные агентские инструкции: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`,
  `QWEN.md`, `GUIDE.md`, `Project.md`, `Plan.md`.
- Абсолютные пути пользователя и реальные пути watched folders.

## Что осталось

1. Дождаться зеленого CI после push.
2. При необходимости выполнить отдельный live smoke MCP-инструментов на уже
   запущенном сервере.
3. Финальный dedup `engineering_rules` делать только после завершения backfill,
   с backup и сначала в dry-run.
4. Для OCR качества нужен обезличенный публичный scanned-PDF fixture; текущие
   тесты покрывают pipeline без публикации реальных документов.

## Запреты и ограничения

- Не публиковать секреты и machine-specific пути.
- Не трогать live index/vector store ради документации.
- Не выполнять destructive DB cleanup при параллельном чтении/записи MCP.
- Не использовать AI-bridge делегирование из этого репозитория.
