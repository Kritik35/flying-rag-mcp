# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — PILOT-PREP-01 (ТЗ FR-TZ-20261116-005 / Подготовка безопасного контура пилота)
**Статус предыдущей ревизии**: Stage 4.2.8 Rev 4 Errata 1 ПРИНЯТ независимым рецензентом (код: `ed0ac010`, отчёты: `ccf0305b`)
**Дата обновления**: 2026-11-16
**Текущая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (tested code commit)**: [`ed0ac010c5739b4a08914063461780a58ca15e38`](https://github.com/Kritik35/flying-rag-mcp/commit/ed0ac010c5739b4a08914063461780a58ca15e38)
**Tree SHA кода**: `699c2283219e4ab3d056ffd3b2a8510ebd5c04ca`
**Отчётный коммит Rev 4 Errata 1**: [`ccf0305bdf1ddc35836e0eb614251961998c986b`](https://github.com/Kritik35/flying-rag-mcp/commit/ccf0305bdf1ddc35836e0eb614251961998c986b) (Tree SHA: `a2d6d872ddbf232bd6156eeee53a36e83ef8c873`)
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Текущий операционный статус**: **`STORAGE_PLAN: READY_FOR_APPROVAL / EMBEDDING_PROFILE: VERIFIED / AWAITING_OPERATOR_APPROVAL`**
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH

---

## 1. Официальные вердикты этапа подготовки пилота (PILOT-PREP-01)

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`STORAGE_PLAN`** | **`READY_FOR_APPROVAL`** | Инвентаризация хранилища завершена. Необходимый объём для независимой копии: ~6.68 ГБ (SQLite 1.485 ГБ + LanceDB 5.138 ГБ + Table Parquet 0.055 ГБ). Свободное место на диске C:: 62.52 ГБ (запас >89%). Выявлено, что поиск производит запись в таблицу `search_cache` базы `metadata.db`, что делает физическую изоляцию обязательной. Устаревшая копия `00_inventory` отвергнута из-за несовпадения хэша (`ea3837f7...` vs `9d1c7364...`). Предложен безопасный вариант создания снимка в зарегистрированном temp. |
| **`EMBEDDING_PROFILE`** | **`VERIFIED`** | Исполняемый файл `llama-server.exe` v0.4.1-dev build 11057 (OpenCL 1.1 / CLBlast FP32, GeForce GT 540M) и модель `Qwen3-Embedding-0.6B-Q8_0.gguf` (639 МБ) найдены. Контракт индекса `index_manifest.json` и кэш SQLite подтверждают размерность 1024. Подготовлена точная команда запуска на 127.0.0.1:8089 (loopback, 2 потока). |
| **`BACKEND_STATE`** | **`SOCKET_TIMEOUT`** | Порт 8089 свободен, фоновых процессов `llama-server` нет, неблокирующий сокет-зонд вернул таймаут. Самовольный запуск не производился. |
| **`DRIVE_DELIVERY_RELIABILITY`** | **`GO`** | Доставка ТЗ `FR-TZ-20261116-005` автоматически зафиксирована монитором `FlyingRAG_Drive_Inbox_Watcher` в 17:45:02 (event ID: `event_FR-TZ-20261116-005_PILOT_v1_920f8018`, SHA256: `920f8018...`). |
| **`NEXT_EXECUTION`** | **`AWAITING_OPERATOR_APPROVAL`** | Подготовительные шаги P0-P3 завершены. Ожидается отдельное разрешение оператора на создание копии корпуса и запуск сервера. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | В рамках задания подготовлен план запуска (3 smoke-пары -> 105 запросов). Поисковые запросы по корпусу не выполнялись. |
| **`CROSS_STORE_RECOVERY`** | **`BLOCKED`** | Распределённый 2PC между SQLite и LanceDB отсутствует (проектное ограничение). |
| **`READER_QUARANTINE_ISOLATION`** | **`READ_ISOLATION_NOT_PROVEN`** | Прямое чтение LanceDB возвращает чанки изолированных файлов (EIG в shadow не фильтрует выдачу). |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Развёртывание на продакшне строго **ЗАПРЕЩЕНО**. Baseline production `9b498bf5dc09e964d035049a53582d52f13cdc95` остаётся неизменным. |

---

## 2. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **198**
- **Успешно**: **198** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1,485,103,104 байт, размер WAL = 0, неизменный sample SHA256 (head_64kb_tail_64kb_sample_plus_size_mtime_journals fingerprint scope; readonly verified).
- **Статус рабочей директории**: **Clean (True)** на момент запуска приёмки.

### Результаты по гейтам (Gates G0 — G8, M2, S5, S6, P2)
| Гейт | Название | Статус | Тестов |
|:---|:---|:---:|:---:|
| **G0** | Environment Isolation & Baseline Anchor | PASSED | 6 / 6 |
| **M2** | Google Drive Inbox Watcher Delivery Reliability, Crash Recovery & Idempotency | PASSED | 18 / 18 |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity (Arrow Schema Rollback Digest) | PASSED | 33 / 33 |
| **G2** | Multi-chunk Sequential Stitching & Coordinate Invariants | PASSED | 9 / 9 |
| **G3** | Formula & Mathematical Integrity Gate | PASSED | 5 / 5 |
| **G4** | Topic Alignment & Evidence Status Synthesis | PASSED | 15 / 15 |
| **G5** | Document Resolution & Read-only SQLite URI | PASSED | 4 / 4 |
| **G6** | Shadow Adapter Safety, Congruence & MCP Path Isolation | PASSED | 35 / 35 |
| **G7** | Adversarial Test Suite & Latency Distribution | PASSED | 25 / 25 |
| **S5** | Synthetic Retrieval Adapter Benchmark (105 Queries) | PASSED | 1 / 1 |
| **S6** | Real Retrieval Shadow Pilot (Section 3.3 / Block P3 Contract) | PASSED | 40 / 40 |
| **P2** | Reader Quarantine Isolation Diagnostic & Cross-Store Contract | PASSED | 1 / 1 |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | PASSED | 5 / 5 |
| **Post**| Database Postflight Integrity Check | PASSED | 1 / 1 |

---

## 3. Профиль производительности (Gate G7)
- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`40.54 ms`**
- **Средняя задержка (CPU)**: **`36.88 ms`**
- **Медиана ($p_{50}$)**: **`37.92 ms`**
- **95-й процентиль ($p_{95}$)**: **`70.09 ms`**
- **99-й процентиль ($p_{99}$)**: **`71.11 ms`**
- **Минимальная задержка**: **`17.79 ms`**
- **Максимальная задержка**: **`71.42 ms`**
- **Суммарное время набора (25 запросов)**: **`1.01 s`**

---

## 4. Сводка выполнения блоков этапа Stage 4.2.8

- **P3 (Shadow Pilot Online Verification & Rejection of False GO)**: Устранены контрпримеры ложного GO; внедрён fail-closed предикат; 12 независимых контрактных сценариев; разделено сырое и нормализованное сравнение полезной нагрузки; проверены счётчики `_executor`; дедлайны реально применены к `_dispatch`; статус `BLOCKED_DEPENDENCY` при отключённом сервисе эмбеддингов.
- **P2 (Quarantine & Reader Protection Truth)**: Диагностический тест доказал возврат чанков из LanceDB при наличии статуса карантина в SQLite; EIG в режиме shadow не фильтрует поисковую выдачу читателю; честно зафиксировано `READ_ISOLATION_NOT_PROVEN`; `CROSS_STORE_RECOVERY: BLOCKED`.
- **M2 (Drive Watcher Delivery Reliability & Reporting Alignment)**: Автоматическая доставка ТЗ Task Scheduler ровно в 12:20:01; безопасный останов `STATE_CORRUPT_HALTED`; восстановление состояния `reconstruct_state_from_artifacts()`; детерминированные ID событий; идемпотентность по хешу; политика повторов согласована с периодическим запуском (`periodic_scheduled_poll`).
- **I3 (LanceDB Canonical Digest & Arrow Scheme Rollback)**: 14 полей схемы Arrow в каноническом дайджесте отката LanceDB; Counter для мультимножеств; детекция подмены провенанса.
- **S5 (Synthetic Retrieval Adapter Benchmark)**: 105 запросов подтверждают 100% побайтную идентичность вывода MCP при среднем оверхеде 0.07 мс.

---

## 5. Оставшиеся дефекты и технические ограничения (Residual Risks)
1. **Недоступность сервиса эмбеддингов**: сервис на порту 8089 отключён (`Socket connection to 127.0.0.1:8089 timed out after 0.5s (TimeoutError: timed out)`). Реальный поиск заблокирован (`BLOCKED_DEPENDENCY`). Требуется запуск оператором: `1. Ensure verified safe/isolated storage environment (OS read-only mode or agreed isolated copy); 2. Launch embedding service (llama-server) on http://127.0.0.1:8089/v1/embeddings with model 'Qwen3-Embedding-0.6B-Q8_0.gguf' (dim=1024).`.
2. **Отсутствие 2PC между SQLite и LanceDB**: при сбое записи в SQLite добавленные векторы в LanceDB не откатываются автоматически (`CROSS_STORE_RECOVERY: BLOCKED`).
3. **Изоляция читателей от карантина не доказана**: прямое векторное чтение LanceDB возвращает чанки изолированных файлов (`READER_QUARANTINE_ISOLATION: READ_ISOLATION_NOT_PROVEN`), поскольку shadow EIG не выполняет активную фильтрацию поисковой выдачи.
4. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`.

---

## 6. Ссылки на подробные технические артефакты
- **Отчёт подготовки пилота PILOT-PREP-01 (ТЗ 005)**: [`reports/PILOT_PREPARATION_005.md`](PILOT_PREPARATION_005.md)
- **Машинно-читаемый план подготовки пилота (JSON)**: [`reports/pilot_preparation_005.json`](pilot_preparation_005.json)
- **Специальный отчёт Revision 4 (Pre-Execution Readonly Gate)**: [`reports/stage4_2_8_rev4_readonly_gate.json`](stage4_2_8_rev4_readonly_gate.json)
- **Полный отчёт приёмки Stage 4.2.8 Rev 4**: [`reports/STAGE4_2_8_REV4_ACCEPTANCE.md`](STAGE4_2_8_REV4_ACCEPTANCE.md)
- **Полный отчёт приёмки Stage 4.2.8 Rev 3**: [`reports/STAGE4_2_8_REV3_ACCEPTANCE.md`](STAGE4_2_8_REV3_ACCEPTANCE.md)
- **Контрактный отчёт Rev 3 (34 сценария: Checks A, B, C)**: [`reports/stage4_2_8_rev3_contract.json`](stage4_2_8_rev3_contract.json)
- **Провенанс Rev 3 (единый конфиг и хеши)**: [`reports/stage4_2_8_rev3_provenance.json`](stage4_2_8_rev3_provenance.json)
- **Полный отчёт приёмки Stage 4.2.8 Rev 2**: [`reports/STAGE4_2_8_REV2_ACCEPTANCE.md`](STAGE4_2_8_REV2_ACCEPTANCE.md)
- **Контрактный отчёт Rev 2 (Checks A1-A4, B1-B5, C1-C4)**: [`reports/stage4_2_8_rev2_contract.json`](stage4_2_8_rev2_contract.json)
- **Провенанс Rev 2 (единый конфиг и хеши)**: [`reports/stage4_2_8_rev2_provenance.json`](stage4_2_8_rev2_provenance.json)
- **Полный отчёт приёмки Stage 4.2.8**: [`reports/STAGE4_2_8_ACCEPTANCE.md`](STAGE4_2_8_ACCEPTANCE.md)
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
