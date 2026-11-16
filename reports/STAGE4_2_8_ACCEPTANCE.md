# FlyingRAG — Отчёт независимой приёмки Stage 4.2.8 (Revision 4 Errata 1)
## Строгая верификация системного temp для корней фикстур (E1-negative R4-06) и пре-экзекьюшн гейт

**Дата приёмки**: 2026-11-16
**Проект**: `Kritik35/flying-rag-mcp`
**Рабочая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (Tested Code Commit)**: [`ed0ac010c5739b4a08914063461780a58ca15e38`](https://github.com/Kritik35/flying-rag-mcp/commit/ed0ac010c5739b4a08914063461780a58ca15e38)
**Tree SHA**: `699c2283219e4ab3d056ffd3b2a8510ebd5c04ca`
**Run ID**: `stage4_2_8_20261116_161822_ed0ac010`
**Базовый анкор (Baseline Anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Снимок аудита (Snapshot Anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Режим приёмки**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH

---

## 1. Официальные вердикты этапа Stage 4.2.8 (Revision 4 Errata 1)

| Проверяемое направление / Компонент | Вердикт | Обоснование |
|:---|:---:|:---|
| **`DRIVE_DELIVERY_RELIABILITY`** | **`GO`** | Блок **M2** закрыт: подтверждена полностью автоматическая доставка ТЗ через Windows Task Scheduler (`FlyingRAG_Drive_Inbox_Watcher`) в спул-каталог. Политика повторов: периодический опрос каждые 5 минут (`periodic_scheduled_poll`), лимит до 5 попыток с переходом в `FAILED_PERMANENT`. |
| **`REAL_RETRIEVAL_SHADOW_PILOT`** | **`BLOCKED`** | Блок P3 (Rev 4 Errata 1) закрыт со статусом **`READONLY_GATE_READY`** / **`BLOCKED_DEPENDENCY`**: 1) Pre-Execution Readonly Gate: проверка допустимости хранилища выполняется ДО первого вызова `execute_bounded_search` и ДО запуска поисковых дочерних процессов; при непроверенном скоупе немедленный отказ со статусом `BLOCKED_READONLY_NOT_PROVEN` и ровно 0 запущенных поисков (Rev 4 Section 2.1, сценарий R4-01); 2) Обязательный veto в `evaluate_pilot_eligibility_predicate`: вердикт `GO` невозможен при непроверенном или заблокированном скоупе (Section 2.2, сценарий R4-02); 3) Устранено ложное повышение статуса по подстроке: наличие `test_fixture` или `isolated_fixture` в пути без подтверждённой регистрации корня оставляет статус `BLOCKED_READONLY_NOT_PROVEN` (Section 2.3, сценарий R4-03); 4) Строгая верификация временной копии: временная копия допускается только при строгой локализации путей внутри зарегистрированного каталога во временной директории ОС (`ISOLATED_COPY_VERIFIED`), выполнение помечается как `CONTRACT_SYNTHETIC` и не претендует на статус пилота рабочего корпуса (Section 2.4-2.5, сценарий R4-04); 5) Настоящий offline preflight остаётся `BLOCKED_DEPENDENCY` с 0 поисков и восстановлением окружения (сценарий R4-05); 6) Errata 1: устранено исключение OR, разрешавшее регистрацию корней вне системного temp; зарегистрированный корень обязан строго локализоваться внутри `tempfile.gettempdir()`, любые внешние каталоги безусловно отклоняются (`BLOCKED_READONLY_NOT_PROVEN`), предотвращая доступ к production через конфигурацию или ручную регистрацию (Rev 4 Errata 1 Section 2, сценарий R4-06). Всего 40 контрактных тестов (100% PASS). Порядок действий оператора: 1. Обеспечить доказанную безопасность/изоляцию контура хранения; 2. Запустить embedding-сервис на http://127.0.0.1:8089/v1/embeddings с моделью 'Qwen3-Embedding-0.6B-Q8_0.gguf' (dim=1024). |
| **`VECTOR_ROLLBACK_INTEGRITY`** | **`GO`** | Блок **I3** (часть 1) закрыт: канонический дайджест строк `_row_canonical_digest(r)` расширен на все 14 полей реальной схемы Arrow/LanceDB. Сверка мультимножеств дайджестов через `collections.Counter` предотвращает скрытое дублирование чанков. Любая подмена данных или провенанса вызывает аварийную остановку `RuntimeError`. |
| **`CROSS_STORE_RECOVERY`** | **`BLOCKED`** | Блок **I3** (часть 2) закрыт с честным вердиктом `BLOCKED`: распределённый двухфазный коммит (2PC) между независимыми хранилищами LanceDB и SQLite отсутствует. При сбое транзакции SQLite после коммита векторов в LanceDB, координатор индексатора изолирует файл статусом `quarantine_failed_indexing` в SQLite, но не откатывает векторы в LanceDB (образуются orphan-чанки). Автоматический сквозной откат не производится. |
| **`READER_QUARANTINE_ISOLATION`** | **`READ_ISOLATION_NOT_PROVEN`** | Блок **P2** закрыт с честным вердиктом `READ_ISOLATION_NOT_PROVEN`: диагностический тест `tests/test_reader_quarantine_isolation.py` доказал, что читатели, выполняющие векторный поиск через LanceDB, напрямую получают чанки документов, находящихся в статусе `quarantine_failed_indexing` в SQLite. В режиме shadow EIG выполняет лишь пассивное асинхронное фоновое наблюдение (`observe_async`) и **НЕ фильтрует результаты поиска, возвращаемые пользователю**. Изоляция читателей не доказана. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Развёртывание на рабочей среде категорически **ЗАПРЕЩЕНО**. Производственный репозиторий `C:\RAG_Acer\repos\flying-rag-mcp` остаётся строго read-only на базовом коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 2. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **198**
- **Успешно**: **198** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1,485,103,104 байт, размер WAL = 0, неизменный sample SHA256 (head_64kb_tail_64kb_sample_plus_size_mtime_journals fingerprint scope; readonly verified).
- **Статус рабочей директории**: **Clean (True)** на момент запуска приёмки.

### Результаты по гейтам (Gates G0 — G8, M2, S5, S6, P2)
| Гейт | Название | Статус | Тестов | Описание |
|:---|:---|:---:|:---:|:---|
| **G0** | Environment Isolation & Baseline Anchor | **PASSED** | 6 / 6 | Изоляция worktree, соответствие baseline production, неизменность snapshot, криптографический префлайт БД |
| **M2** | Google Drive Inbox Watcher Delivery Reliability, Crash Recovery & Idempotency | **PASSED** | 18 / 18 | Надёжность доставки ТЗ через Google Drive: Task Scheduler в 12:20:01 (18 525 байт), безопасный останов STATE_CORRUPT_HALTED, reconstruct_state_from_artifacts, детерминированный ID события, идемпотентность по хешу, периодический опрос (5 мин, макс 5) |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity | **PASSED** | 33 / 33 | Глубокая сверка отката LanceDB (полный канонический дайджест всех 14 полей Arrow, сверка мультимножеств векторов и строк, контракт окна сбоев) |
| **G2** | Multi-chunk Sequential Stitching & Coordinate Invariants | **PASSED** | 9 / 9 | Склейка смежных чанков, инварианты координат codepoints, отказ от конкатенации без перекрытия |
| **G3** | Formula & Mathematical Integrity Gate | **PASSED** | 5 / 5 | Детекция математических уравнений, изоляция ссылок без тела формулы, отказ скалярных присвоений |
| **G4** | Topic Alignment & Evidence Status Synthesis | **PASSED** | 15 / 15 | Защита от ложных отказов, детекция формульных запросов с понижением статуса, обработка общих тем |
| **G5** | Document & Edition Disambiguation / SQLite RO URI | **PASSED** | 4 / 4 | Точные границы токенов (СП 7 vs СП 70), детекция мультиредакций, read-only enforce в SQLite |
| **G6** | Shadow Adapter Safety, Congruence & MCP Path Isolation | **PASSED** | 35 / 35 | Shadow Adapter: детерминированное разрешение путей control_file, bounded shutdown, cancel pending, fail-safe disabled |
| **G7** | Adversarial Test Suite & Latency Distribution | **PASSED** | 25 / 25 | Adversarial Test Suite: 25 стресс-запросов, средняя задержка 40.54 мс (Wall), медиана 37.92 мс, p95 70.09 мс |
| **S5** | Synthetic Retrieval Adapter Benchmark (105 Queries) | **PASSED** | 1 / 1 | Synthetic Retrieval Adapter Benchmark: 105 запросов на синтетических фикстурах, 100% побайтная сериализация, rank match, оверхед диспетчеризации 0.07 мс |
| **S6** | Real Retrieval Shadow Pilot (Section 3.3 / Block P3) | **PASSED** | 40 / 40 | Real Retrieval Shadow Pilot: 12 контрактных сценариев (Block P3), устранение ложного GO, fail-closed предикат, честная фиксация недоступности бэкенда (порт 8089/13305) со статусом BLOCKED_DEPENDENCY |
| **P2** | Reader Quarantine Isolation Diagnostic & Cross-Store Contract | **PASSED** | 1 / 1 | Reader Quarantine Isolation Diagnostic: доказательство чтения изолированных чанков из LanceDB при сбое в SQLite, подтверждение пассивной роли shadow EIG (без фильтрации пользовательской выдачи), честная фиксация READ_ISOLATION_NOT_PROVEN |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | **PASSED** | 5 / 5 | Production Read-Only Source Fidelity & OOXML Audit: инварианты СП 7 / СП 60, пропуск OMML в python-docx |
| **Post**| Database Postflight Integrity Check | **PASSED** | 1 / 1 | Database Postflight Integrity Check: полное совпадение контрольных сумм и mtime базы данных до и после всех тестов |

---

## 3. Детальный отчёт по блоку P3 (Устранение ложного GO, контрактные сценарии и критерии приёмки)

1. **Устранение дефектов онлайна этапа 4.2.7**:
   - В Stage 4.2.7 проверка пула обращалась к несуществующему атрибуту `adapter._pool`, в то время как настоящий адаптер `ShadowEvidenceIntegrityGate` использует `_executor` (`ThreadPoolExecutor`). В результате ожидание завершения наблюдателя не срабатывало, `shadow_submitted` увеличивался безусловно, а `errors` и `dropped` были захардкожены нулями.
   - В Stage 4.2.8 реализовано прямое отслеживание дельт счётчиков адаптера (`adapter.submitted_count`, `adapter.processed_count`, `adapter.error_count`, `adapter.drop_count`) и безопасное ожидание завершения задач через `adapter._active_futures` без вызова деструктивного `shutdown()`.
2. **Fail-Closed предикат приёмки (Eligibility Predicate)**:
   - В соответствии с разделом 3 ТЗ `FR-TZ-20261116-004`, вердикт `GO` выставляется строго при одновременном выполнении условий:
     - `real_search_path_verified` (реальный путь поиска через `_dispatch`);
     - `successful_search_pairs_completed == total_queries`;
     - `no_search_errors` (`search_errors == 0`, исключены ответы с `error` payload);
     - `normalized_payload_mismatches == 0`;
     - `rank_mismatches == 0`;
     - `off_observer_calls == 0` (в режиме OFF наблюдатель строго не вызывается);
     - `shadow_submitted == total_queries` и `shadow_processed == total_queries`;
     - `shadow_errors == 0` и `shadow_dropped == 0`;
     - `all_deadlines_enforced` (все дедлайны соблюдены);
     - `readonly_scope_verified` (БД не модифицирована).
   - При невыполнении любого условия вердикт не может быть `GO`.
3. **Разделение сырого и нормализованного сравнения**:
   - Функция `compare_payloads` возвращает раздельные флаги: `raw_equal` (побайтно идентичный JSON) и `normalized_equal` (совпадение после удаления задокументированных динамических полей: `request_id`, `wall_latency_ms`, `cpu_latency_ms`).
   - Исключена ложная декларация о «побайтном равенстве» при наличии динамических меток времени.
4. **Контрактный тестовый набор (12 сценариев)**:
   - В `tests/test_real_retrieval_shadow_pilot.py` реализованы 12 тестов, проверяющих:
     1. Отсутствие адаптера в режиме ON -> отказ в GO (`BLOCKED_SHADOW_INIT` / `FAILED`).
     2. Отклонение задачи или незавершённое наблюдение -> отказ в GO.
     3. Ошибки или сбросы задач в наблюдателе -> отражение в статистике и отказ в GO.
     4. Одинаковые ответы с ошибкой (error payload) -> отказ в GO, фиксация сбоя поиска.
     5. Успешный fixture dispatch с подтверждённым наблюдением -> корректный contract success.
     6. Перестановка результатов -> детекция `rank_mismatch`.
     7. Различие полей `request_id` / латентности -> `raw_equal=False`, `normalized_equal=True`.
     8. Зависший поиск -> строгое прерывание по дедлайну (`SEARCH_DEADLINE_EXCEEDED`).
     9. Принудительно отключённый бэкенд -> `BLOCKED_DEPENDENCY`, 0 выполненных поисков.
     10. Доступный бэкенд -> юнит-тесты не падают из-за ожидания offline.
     11. Исключения при диспетчеризации -> восстановление переменных окружения и очистка ресурсов.
     12. Режим OFF -> строго нулевое количество вызовов наблюдателя.
5. **Диагностика бэкенда эмбеддингов**:
   - Эффективная конфигурация определена из производственного конфига: адрес `http://127.0.0.1:8089/v1/embeddings`, модель `Qwen3-Embedding-0.6B-Q8_0.gguf`, размерность 1024.
   - Быстрый сокет-префлайт с таймаутом 0.5с установил отсутствие слушающего сервиса (`Socket connection to 127.0.0.1:8089 timed out after 0.5s (TimeoutError: timed out)`).
   - Честно зафиксирован статус `BLOCKED_DEPENDENCY`, 0 выполненных поисков.
   - Действие оператора: `1. Ensure verified safe/isolated storage environment (OS read-only mode or agreed isolated copy); 2. Launch embedding service (llama-server) on http://127.0.0.1:8089/v1/embeddings with model 'Qwen3-Embedding-0.6B-Q8_0.gguf' (dim=1024).`.

---

## 4. Детальный отчёт по блоку P2 (Честная изоляция читателей и статус карантина)

1. **Техническая реальность прямого чтения LanceDB**:
   - Архитектура `search_documents()` в FlyingRAG выполняет векторный поиск напрямую по таблице `rag_chunks` / `documents_1024` в LanceDB. Векторный индекс LanceDB не выполняет runtime SQL-join с таблицей `files` в SQLite.
   - Диагностический тест `tests/test_reader_quarantine_isolation.py` доказал, что читатель получает чанки документов, находящихся в карантине SQLite (`doc_p2_1`).
2. **Пассивная роль Shadow EIG**:
   - В режиме shadow Evidence Integrity Gate выполняет исключительно пассивное асинхронное фоновое наблюдение (`observe_async`).
   - Shadow EIG **не фильтрует, не модифицирует и не блокирует результаты поиска**, возвращаемые пользователю или MCP-клиенту.
3. **Вердикты**:
   - `READER_QUARANTINE_ISOLATION: READ_ISOLATION_NOT_PROVEN`
   - `CROSS_STORE_RECOVERY: BLOCKED`

---

## 5. Детальный отчёт по блоку M2 (Надёжность доставки ТЗ и согласование отчётности)

1. **Автоматическая доставка ТЗ планировщиком Task Scheduler**:
   - Задача Windows Task Scheduler `FlyingRAG_Drive_Inbox_Watcher` зафиксировала файл `FR-TZ-20261116-004_Stage4.2.8_9ffecf68_FlyingRAG.txt` (18 525 байт, SHA256 `fbedfa1ea841a85ba1a8ed3656f78bbd302dc9eeec125778fdcb01b311d2603c`) ровно в 12:20:01 (09:20:01 UTC).
   - Файл автоматически спулирован в `inbox_spool/FR-TZ-20261116-004_Stage4.2.8_9ffecf68_FlyingRAG_v1_fbedfa1e.txt`.
   - Ручные вызовы `--bootstrap` или `--poll-once` не потребовались.
2. **Согласование политики повторов с кодом**:
   - В отчётности устранено упоминание нереализованного экспоненциального бэкоффа (`linear_1.5x_jitter`).
   - Зафиксирована реальная логика: периодический запуск по расписанию (`periodic_scheduled_poll`, интервал 5 минут, лимит до 5 попыток с переходом в `FAILED_PERMANENT`).

---

## 6. Профиль производительности (Gate G7)

- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`40.54 ms`**
- **Средняя задержка (CPU Time)**: **`36.88 ms`**
- **Медиана ($p_{50}$)**: **`37.92 ms`**
- **95-й процентиль ($p_{95}$)**: **`70.09 ms`**
- **99-й процентиль ($p_{99}$)**: **`71.11 ms`**
- **Минимальная задержка**: **`17.79 ms`**
- **Максимальная задержка**: **`71.42 ms`**
- **Суммарное время набора (25 запросов)**: **`1.01 s`**

---

## 7. Оставшиеся дефекты и риски (Top Residual Risks)

1. **Недоступность сервиса эмбеддингов**: сервис на порту 8089 отключён (`Socket connection to 127.0.0.1:8089 timed out after 0.5s (TimeoutError: timed out)`). Реальный поиск заблокирован (`BLOCKED_DEPENDENCY`). Требуется запуск оператором: `1. Ensure verified safe/isolated storage environment (OS read-only mode or agreed isolated copy); 2. Launch embedding service (llama-server) on http://127.0.0.1:8089/v1/embeddings with model 'Qwen3-Embedding-0.6B-Q8_0.gguf' (dim=1024).`.
2. **Отсутствие 2PC между SQLite и LanceDB**: при сбое записи в SQLite добавленные векторы в LanceDB не откатываются автоматически (`CROSS_STORE_RECOVERY: BLOCKED`).
3. **Изоляция читателей от карантина не доказана**: прямое векторное чтение LanceDB возвращает чанки изолированных файлов (`READER_QUARANTINE_ISOLATION: READ_ISOLATION_NOT_PROVEN`), поскольку shadow EIG не выполняет активную фильтрацию поисковой выдачи.
4. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`.

---

## 8. Ссылки на подробные технические артефакты

- **Машинно-читаемые результаты гейтов**: [`reports/stage4_2_8_gate_results.json`](stage4_2_8_gate_results.json)
- **Матрица тестов (198 проверок)**: [`reports/stage4_2_8_test_matrix.json`](stage4_2_8_test_matrix.json)
- **Отчёт реального пилота поиска**: [`reports/stage4_2_8_real_search_pilot.json`](stage4_2_8_real_search_pilot.json)
- **Протокол контрактных отказов и контрпримеров**: [`reports/stage4_2_8_contract_failures.json`](stage4_2_8_contract_failures.json)
- **Отчёт службы доставки Drive Watcher**: [`reports/stage4_2_8_watcher_delivery.json`](stage4_2_8_watcher_delivery.json)
- **Диагностика изоляции читателей и карантина**: [`reports/stage4_2_8_reader_isolation.json`](stage4_2_8_reader_isolation.json)
- **Доказательства безопасности индексатора**: [`reports/stage4_2_8_indexer_recovery.json`](stage4_2_8_indexer_recovery.json)
- **Провенанс и криптографические контрольные суммы**: [`reports/stage4_2_8_provenance.json`](stage4_2_8_provenance.json)
- **Достоверность первоисточников**: [`reports/stage4_2_8_source_fidelity.json`](stage4_2_8_source_fidelity.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
