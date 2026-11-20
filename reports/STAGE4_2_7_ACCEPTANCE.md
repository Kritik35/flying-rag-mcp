# FlyingRAG — Отчёт независимой приёмки Stage 4.2.7
## Настоящий ON/OFF-пилот, честная изоляция читателей и завершение проверок Stage 4.2.6

**Дата приёмки**: 2026-11-16
**Проект**: `Kritik35/flying-rag-mcp`
**Рабочая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (Tested Code Commit)**: [`b4e33be4bfb632b63108a6bfb1364f1531f28da9`](https://github.com/Kritik35/flying-rag-mcp/commit/b4e33be4bfb632b63108a6bfb1364f1531f28da9)
**Tree SHA**: `66ddf0299f822c73e034e15facf088a61969bc43`
**Run ID**: `stage4_2_7_20261116_114346_b4e33be4`
**Базовый анкор (Baseline Anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Снимок аудита (Snapshot Anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Режим приёмки**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH

---

## 1. Официальные вердикты этапа Stage 4.2.7

| Проверяемое направление / Компонент | Вердикт | Обоснование |
|:---|:---:|:---|
| **`DRIVE_DELIVERY_RELIABILITY`** | **`GO`** | Блок **M2** закрыт: подтверждена полностью автоматическая доставка ТЗ `FR-TZ-20261116-003_Stage4.2.7_cf2fb139_FlyingRAG.txt` через Windows Task Scheduler (`FlyingRAG_Drive_Inbox_Watcher`) ровно в 11:00:00 (SHA256: `21b452ef...`, 18 178 байт) без ручного вмешательства. Реализована защита от повреждения `state.json` (безопасный останов `STATE_CORRUPT_HALTED` с архивацией в `.corrupt_<timestamp>` без перезаписи файла), функция `reconstruct_state_from_artifacts()` для восстановления состояния из артефактов без генерации дублей, детерминированные ID событий `event_{stem}_v{version}_{sha256[:8]}`, идемпотентность по хешу содержимого (пропуск повторных событий при неизменном SHA256) и персистентный счетчик повторов с переходом в `FAILED_PERMANENT` после 5 попыток. |
| **`REAL_RETRIEVAL_SHADOW_PILOT`** | **`BLOCKED`** | Блок **P1** закрыт с честным вердиктом `BLOCKED` (`BLOCKED_DEPENDENCY`): реализован истинный парный запуск OFF (`FLYING_RAG_SHADOW_EIG=0`) vs ON (`FLYING_RAG_SHADOW_EIG=1`) через реальный диспетчер `_dispatch`, проверка наблюдателя с `request_id`, честный компаратор рангов стабильных идентификаторов (с проверкой обнаружения перестановок рангов), компаратор пользовательской нагрузки и жесткие неблокирующие дедлайны (2.0s префлайт, 5.0s запрос через изолированный daemon-поток, исключающий зависания). Локальный сервис эмбеддингов Lemonade (`http://localhost:13305/api/v1/embeddings`) отключён (`[WinError 10061] Connection refused`). В строгом соответствии с ТЗ зафиксирован честный статус `BLOCKED_DEPENDENCY` с 0 выполненных поисков, без подмены выдачи моками или SELECT LIMIT. |
| **`VECTOR_ROLLBACK_INTEGRITY`** | **`GO`** | Блок **I3** (часть 1) закрыт: канонический дайджест строк `_row_canonical_digest(r)` расширен на все 14 полей реальной схемы Arrow/LanceDB (`chunk_id`, `doc_id`, `text`, `text_hash`, `source_path`, `file_name`, `format`, `created_at`, `modified_at`, `section`, `namespace`, `parent_id`, `metadata`, `vector`). Сверка мультимножеств дайджестов через `collections.Counter` предотвращает скрытое дублирование чанков. Любая подмена данных или провенанса (`source_path`, `parent_id`, `namespace`) вызывает аварийную остановку `RuntimeError`. |
| **`CROSS_STORE_RECOVERY`** | **`BLOCKED`** | Блок **I3** (часть 2) закрыт с честным вердиктом `BLOCKED`: распределённый двухфазный коммит (2PC) между независимыми хранилищами LanceDB и SQLite в архитектуре FlyingRAG отсутствует. При сбое транзакции SQLite после успешного коммита векторов в LanceDB, координатор индексатора изолирует файл статусом `quarantine_failed_indexing` в SQLite, но не откатывает векторы в LanceDB (образуются «сиротские» чанки-orphans). Автоматический сквозной откат не производится. |
| **`READER_QUARANTINE_ISOLATION`** | **`READ_ISOLATION_NOT_PROVEN`** | Блок **P2** закрыт с честным вердиктом `READ_ISOLATION_NOT_PROVEN`: диагностический тест `tests/test_reader_quarantine_isolation.py` доказал, что читатели, выполняющие векторный поиск через `search_documents()` / LanceDB, напрямую получают чанки документов, находящихся в статусе `quarantine_failed_indexing` в SQLite. В режиме shadow EIG выполняет лишь пассивное асинхронное фоновое наблюдение (`observe_async`) и **НЕ фильтрует результаты поиска, возвращаемые пользователю**. Ложные заявления об «изоляции читателей фильтрацией EIG» полностью удалены из отчётности. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Развёртывание на рабочей среде категорически **ЗАПРЕЩЕНО**. Производственный репозиторий `<PRODUCTION_DIR>/flying-rag-mcp` остаётся строго read-only на базовом коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 2. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **163**
- **Успешно**: **163** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1,485,103,104 байт, хеш среза и нулевой размер WAL неизменны.
- **Статус рабочей директории**: **Clean (True)** на момент запуска приёмки.

### Результаты по гейтам (Gates G0 — G8, M2, S5, S6, P2)
| Гейт | Название | Статус | Тестов | Описание |
|:---|:---|:---:|:---:|:---|
| **G0** | Environment Isolation & Baseline Anchor | **PASSED** | 6 / 6 | Изоляция worktree, соответствие baseline production, неизменность snapshot, криптографический префлайт БД |
| **M2** | Google Drive Inbox Watcher Delivery Reliability, Crash Recovery & Idempotency | **PASSED** | 18 / 18 | Надёжность доставки ТЗ через Google Drive: Task Scheduler в 11:00:00 (18 178 байт), безопасный останов STATE_CORRUPT_HALTED, reconstruct_state_from_artifacts, детерминированный ID события, идемпотентность по хешу, лимит повторов FAILED_PERMANENT |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity | **PASSED** | 33 / 33 | Глубокая сверка отката LanceDB (полный канонический дайджест всех 14 полей Arrow, сверка мультимножеств векторов и строк, контракт окна сбоев) |
| **G2** | Multi-chunk Sequential Stitching & Coordinate Invariants | **PASSED** | 9 / 9 | Склейка смежных чанков, инварианты координат codepoints, отказ от конкатенации без перекрытия |
| **G3** | Formula & Mathematical Integrity Gate | **PASSED** | 5 / 5 | Детекция математических уравнений, изоляция ссылок без тела формулы, отказ скалярных присвоений |
| **G4** | Topic Alignment & Evidence Status Synthesis | **PASSED** | 15 / 15 | Защита от ложных отказов, детекция формульных запросов с понижением статуса, обработка общих тем |
| **G5** | Document & Edition Disambiguation / SQLite RO URI | **PASSED** | 4 / 4 | Точные границы токенов (СП 7 vs СП 70), детекция мультиредакций, read-only enforce в SQLite |
| **G6** | Shadow Adapter Safety, Congruence & MCP Path Isolation | **PASSED** | 35 / 35 | Shadow Adapter: детерминированное разрешение путей control_file, bounded shutdown, cancel pending, fail-safe disabled |
| **G7** | Adversarial Test Suite & Latency Distribution | **PASSED** | 25 / 25 | Adversarial Test Suite: 25 стресс-запросов, средняя задержка 51.77 мс (Wall), медиана 49.28 мс, p95 89.28 мс |
| **S5** | Synthetic Retrieval Adapter Benchmark (105 Queries) | **PASSED** | 1 / 1 | Synthetic Retrieval Adapter Benchmark: 105 запросов на синтетических фикстурах, 100% побайтная сериализация, rank match, оверхед диспетчеризации 0.22 мс |
| **S6** | Real Retrieval Shadow Pilot (Section 3.3 / Block P1) | **PASSED** | 5 / 5 | Real Retrieval Shadow Pilot: реальный парный контракт он/офф через _dispatch, регистрация наблюдателя с request_id, компаратор рангов, таймауты 2.0s/5.0s, фиксация недоступности Lemonade (localhost:13305) со статусом BLOCKED_DEPENDENCY |
| **P2** | Reader Quarantine Isolation Diagnostic & Cross-Store Contract | **PASSED** | 1 / 1 | Reader Quarantine Isolation Diagnostic: доказательство чтения изолированных чанков из LanceDB при сбое в SQLite, подтверждение пассивной роли shadow EIG (без фильтрации пользовательской выдачи), честная фиксация READ_ISOLATION_NOT_PROVEN |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | **PASSED** | 5 / 5 | Production Read-Only Source Fidelity & OOXML Audit: инварианты СП 7 / СП 60, пропуск OMML в python-docx |
| **Post**| Database Postflight Integrity Check | **PASSED** | 1 / 1 | Database Postflight Integrity Check: полное совпадение контрольных сумм и mtime базы данных до и после всех тестов |

---

## 3. Детальный отчёт по блоку P1 (Настоящий парный пилот он/офф и гарантии дедлайна)

1. **Реальный парный запуск через диспетчер MCP**:
   - Каждый запрос выполняется строго в двух режимах: сначала с `FLYING_RAG_SHADOW_EIG=0` (теневой режим выключен), затем с `FLYING_RAG_SHADOW_EIG=1` (теневой режим включён).
   - Вызовы осуществляются через реальный диспетчер `_dispatch` инструмента `search_documents`.
   - В тестах `test_p1_01_off_vs_on_true_dispatch_pair` и `test_p1_02_rank_comparator_permutations_detected` подтверждено:
     - При выключенном shadow наблюдатель `observe_async` **не вызывается**.
     - При включенном shadow наблюдатель вызывается ровно один раз на запрос с переданным уникальным `request_id`.
     - При совпадении рангов и полезной нагрузки компаратор подтверждает идентичность выдачи.
     - При искусственной перестановке рангов компаратор корректно фиксирует несоответствие (`rank_mismatch`).
2. **Гарантии дедлайна без зависания процессов (Non-blocking Timeout)**:
   - Префлайт ограничен дедлайном в 2.0 секунды, а выполнение поискового запроса — 5.0 секундами.
   - Вызов изолирован в daemon-потоке `threading.Thread(daemon=True)`. Использование `ThreadPoolExecutor.shutdown(wait=True)` полностью устранено, что исключает блокировку процесса при зависании сетевого сокета или бэкенда на Windows.
   - Проверено тестом `test_p1_03_deadline_timeout_enforced_strictly_under_2s`.
3. **Честный префлайт и диагностика отключенного бэкенда**:
   - Префлайт динамически считывает эффективную конфигурацию через `config_loader.load_config()`.
   - При недоступности сервиса Lemonade (`http://localhost:13305/api/v1/embeddings`, `[WinError 10061]`) выставляется статус `BLOCKED_DEPENDENCY` и вердикт `BLOCKED`.
   - Количество выполненных реальных поисков честно равно 0 (`actual_searches_executed = 0`).
   - Чётко сформулированы требуемые действия оператора: запустить сервис Lemonade на порту 13305 перед началом пилотной эксплуатации.
   - Проверено тестами `test_p1_04_offline_preflight_blocks_pilot_honestly` и `test_p1_05_call_counter_reflects_actual_searches`.

---

## 4. Детальный отчёт по блоку P2 (Честная изоляция читателей и статус карантина)

1. **Техническая реальность прямого чтения LanceDB**:
   - Архитектура `search_documents()` в FlyingRAG выполняет векторный поиск напрямую по таблице `rag_chunks` в LanceDB. Векторный индекс LanceDB не выполняет runtime SQL-join с таблицей `files` в SQLite.
   - Диагностический тест `tests/test_reader_quarantine_isolation.py` смоделировал следующий сценарий:
     1. Создана консистентная база данных.
     2. Чанк документа `doc_p2_1` успешно записан в LanceDB.
     3. При коммите родительских чанков в SQLite смоделирован сбой -> файл переведён в статус `quarantine_failed_indexing`, таблица `parent_chunks` пуста.
     4. Читатель выполняет векторный поиск через LanceDB.
     5. Читатель **успешно получает чанк `doc_p2_1`**, несмотря на карантинный статус файла в SQLite.
2. **Пассивная роль Shadow EIG**:
   - В режиме shadow Evidence Integrity Gate выполняет исключительно пассивное асинхронное фоновое наблюдение (`observe_async`).
   - Shadow EIG **не фильтрует, не модифицирует и не блокирует результаты поиска**, возвращаемые пользователю или MCP-клиенту.
3. **Удаление недостоверных заявлений и честная фиксация вердиктов**:
   - Из отчетов и `LATEST.md` удалены все вводящие в заблуждение формулировки о том, что «читатели защищены фильтрацией EIG».
   - Зафиксировано: статус карантина в SQLite изолирует файл от повторной индексации, но **не обеспечивает изоляцию читателей от векторного поиска**.
   - Официальный вердикт: **`READER_QUARANTINE_ISOLATION: READ_ISOLATION_NOT_PROVEN`**.
   - Вердикт **`CROSS_STORE_RECOVERY: BLOCKED`** подтверждён.

---

## 5. Детальный отчёт по блоку M2 (Устойчивость вотчера к сбоям, повреждению состояния и идемпотентность)

1. **Автоматическая доставка ТЗ планировщиком Task Scheduler**:
   - Задача Windows Task Scheduler `FlyingRAG_Drive_Inbox_Watcher` с интервалом 5 минут зафиксировала файл `FR-TZ-20261116-003_Stage4.2.7_cf2fb139_FlyingRAG.txt` (18 178 байт, SHA256 `21b452efe5d873067d6b60c0b07f2ede37ae08d0bd5b2c241fd5478eba477e32`) ровно в 11:00:00 (08:00:00 UTC).
   - Файл автоматически сохранён в `inbox_spool/FR-TZ-20261116-003_Stage4.2.7_cf2fb139_FlyingRAG_v1_21b452ef.txt`.
   - Ручные вызовы `--bootstrap` или `--poll-once` не потребовались.
2. **Безопасный останов при повреждении состояния (Safe Halt)**:
   - При обнаружении синтаксических ошибок или повреждений в `state.json` создаётся архивная копия `state.json.corrupt_<timestamp>`.
   - Выставляется флаг `_state_is_corrupt = True`, и опрос безопасно останавливается со статусом `STATE_CORRUPT_SAFE_HALT`.
   - Исходный файл `state.json` **не перезаписывается и не затирается**, предотвращая потерю истории подтверждённых файлов.
   - Покрыто тестом `test_m2_01_corrupt_state_archives_and_halts_safely`.
3. **Восстановление состояния из артефактов (State Reconstruction)**:
   - Метод `reconstruct_state_from_artifacts()` сканирует директории `notifications/` и `inbox_spool/` и воссоздаёт словарь `tracked_files` и список событий `processed_events`.
   - Повторные дублирующие уведомления не генерируются.
   - Покрыто тестом `test_m2_02_reconstruct_state_from_artifacts`.
4. **Детерминированные ID событий и идемпотентность по хешу**:
   - Идентификаторы событий строятся по шаблону `event_{stem[:24]}_v{version}_{sha256[:8]}` на основе хеша содержимого.
   - Если файл получил новое время изменения `mtime` (например, при облачной синхронизации), но его SHA256 не изменился, запись обновляется без инкремента версии и без повторного события.
   - Покрыто тестом `test_m2_03_content_hash_idempotency_ignores_spurious_mtime_touch`.
5. **Персистентный лимит повторных попыток**:
   - Счетчик `retry_count` сохраняется на диске. После 5 неудачных попыток чтения файл переводится в терминальный статус `FAILED_PERMANENT`.
   - При последующих опросах файл пропускается до тех пор, пока оператор не изменит его содержимое.
   - Покрыто тестом `test_m2_04_persistent_retry_budget_exhaustion_marks_failed_permanent`.

---

## 6. Профиль производительности (Gate G7)

- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`51.77 ms`**
- **Средняя задержка (CPU Time)**: **`41.88 ms`**
- **Медиана ($p_{50}$)**: **`49.28 ms`**
- **95-й процентиль ($p_{95}$)**: **`89.28 ms`**
- **99-й процентиль ($p_{99}$)**: **`100.25 ms`**
- **Минимальная задержка**: **`23.52 ms`**
- **Максимальная задержка**: **`102.55 ms`**
- **Суммарное время набора (25 запросов)**: **`1.29 s`**

---

## 7. Оставшиеся дефекты и риски (Top Residual Risks)

1. **Недоступность Lemonade Embedding Server**: локальный сервис на `localhost:13305` отключён (`[WinError 10061]`). Реальный поиск заблокирован (`BLOCKED_DEPENDENCY`). Требуется запуск сервиса оператором перед включением пилота.
2. **Отсутствие 2PC между SQLite и LanceDB**: при сбое записи в SQLite добавленные векторы в LanceDB не откатываются автоматически (`CROSS_STORE_RECOVERY: BLOCKED`).
3. **Изоляция читателей от карантина не доказана**: прямое векторное чтение LanceDB возвращает чанки изолированных файлов (`READER_QUARANTINE_ISOLATION: READ_ISOLATION_NOT_PROVEN`), поскольку shadow EIG не выполняет активную фильтрацию поисковой выдачи.
4. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`.

---

## 8. Ссылки на подробные технические артефакты

- **Машинно-читаемые результаты гейтов**: [`reports/stage4_2_7_gate_results.json`](stage4_2_7_gate_results.json)
- **Матрица тестов (163 проверок)**: [`reports/stage4_2_7_test_matrix.json`](stage4_2_7_test_matrix.json)
- **Отчёт службы доставки Drive Watcher**: [`reports/stage4_2_7_watcher_delivery.json`](stage4_2_7_watcher_delivery.json)
- **Отчёт реального пилота поиска**: [`reports/stage4_2_7_real_search_pilot.json`](stage4_2_7_real_search_pilot.json)
- **Диагностика изоляции читателей и карантина**: [`reports/stage4_2_7_reader_isolation.json`](stage4_2_7_reader_isolation.json)
- **Доказательства безопасности индексатора**: [`reports/stage4_2_7_indexer_recovery.json`](stage4_2_7_indexer_recovery.json)
- **Провенанс и криптографические контрольные суммы**: [`reports/stage4_2_7_provenance.json`](stage4_2_7_provenance.json)
- **Достоверность первоисточников**: [`reports/stage4_2_7_source_fidelity.json`](stage4_2_7_source_fidelity.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
