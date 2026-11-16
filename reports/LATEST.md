# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — Revision 4 (Предварительный допуск read-only до поиска)
**Дата обновления**: 2026-11-16
**Текущая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (tested code commit)**: [`978901519a426d1ae1cc2c186d78d05db0d82aa2`](https://github.com/Kritik35/flying-rag-mcp/commit/978901519a426d1ae1cc2c186d78d05db0d82aa2)
**Tree SHA кода**: `3c09e63cbfd9b43ee70bfde387c93dd883cfd463`
**Предыдущий отчётный коммит (source report commit Rev 3)**: [`b1ce48e66ad6e3b663d26b26b0b19cd92dfb0518`](https://github.com/Kritik35/flying-rag-mcp/commit/b1ce48e66ad6e3b663d26b26b0b19cd92dfb0518) (Tree SHA: `a5c4601b8dd9392c1615be23ff65f55e1c6df419`)
**Предшествующий отчётный коммит Rev 2**: [`88ed13aed4b9647ea8db4292caa575f02c103042`](https://github.com/Kritik35/flying-rag-mcp/commit/88ed13aed4b9647ea8db4292caa575f02c103042) (Tree SHA: `f6edf139481a48c4cf2a4cdbecbed62b7a931f3e`)
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Run ID**: `stage4_2_8_20261116_154502_97890151`
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH

---

## 1. Официальные вердикты этапа Stage 4.2.8 (Revision 4)

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`DRIVE_DELIVERY_RELIABILITY`** | **`GO`** | Блок M2 закрыт: автоматическая доставка ТЗ `FR-TZ-20261116-004` Task Scheduler подтверждена в 12:20:01 (SHA256: `fbedfa1e...`, 18 525 байт). Политика повторов согласована с периодическим запуском (интервал 5 минут, макс 5 попыток). |
| **`REAL_RETRIEVAL_SHADOW_PILOT`** | **`BLOCKED`** | Блок P3 (Rev 4) закрыт со статусом **`READONLY_GATE_READY`** / **`BLOCKED_DEPENDENCY`**: 1) Pre-Execution Readonly Gate: проверка допустимости хранилища выполняется ДО первого вызова `execute_bounded_search` и ДО запуска поисковых дочерних процессов; при непроверенном скоупе немедленный отказ со статусом `BLOCKED_READONLY_NOT_PROVEN` и ровно 0 запущенных поисков (Rev 4 Section 2.1, сценарий R4-01); 2) Обязательный veto в `evaluate_pilot_eligibility_predicate`: вердикт `GO` невозможен при непроверенном или заблокированном скоупе (Section 2.2, сценарий R4-02); 3) Устранено ложное повышение статуса по подстроке: наличие `test_fixture` или `isolated_fixture` в пути без подтверждённой регистрации корня оставляет статус `BLOCKED_READONLY_NOT_PROVEN` (Section 2.3, сценарий R4-03); 4) Строгая верификация временной копии: временная копия допускается только при строгой локализации путей внутри зарегистрированного каталога во временной директории ОС (`ISOLATED_COPY_VERIFIED`), выполнение помечается как `CONTRACT_SYNTHETIC` и не претендует на статус пилота рабочего корпуса (Section 2.4-2.5, сценарий R4-04); 5) Настоящий offline preflight остаётся `BLOCKED_DEPENDENCY` с 0 поисков и восстановлением окружения (сценарий R4-05). Всего 39 контрактных тестов (100% PASS). Порядок действий оператора: 1. Обеспечить доказанную безопасность/изоляцию контура хранения; 2. Запустить embedding-сервис на http://127.0.0.1:8089/v1/embeddings с моделью 'Qwen3-Embedding-0.6B-Q8_0.gguf' (dim=1024). |
| **`VECTOR_ROLLBACK_INTEGRITY`** | **`GO`** | Канонический дайджест всех 14 полей Arrow, сверка мультимножеств векторов и строк, защита от подмены провенанса. |
| **`CROSS_STORE_RECOVERY`** | **`BLOCKED`** | Распределённый 2PC между SQLite и LanceDB отсутствует. При сбое индексации SQLite помечает файл как `quarantine_failed_indexing`, но в LanceDB остаются orphan-векторы. Автоматический межбазовый откат не производится. |
| **`READER_QUARANTINE_ISOLATION`** | **`READ_ISOLATION_NOT_PROVEN`** | Блок P2 закрыт: прямое чтение LanceDB возвращает чанки документов, находящихся в карантине SQLite. EIG в режиме shadow выполняет лишь асинхронное фоновое наблюдение (`observe_async`) и НЕ фильтрует поисковую выдачу пользователю. Изоляция читателей не доказана. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Развёртывание на продакшне строго **ЗАПРЕЩЕНО**. Baseline production `9b498bf5dc09e964d035049a53582d52f13cdc95` остаётся неизменным. |

---

## 2. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **197**
- **Успешно**: **197** (100.0%)
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
| **S6** | Real Retrieval Shadow Pilot (Section 3.3 / Block P3 Contract) | PASSED | 39 / 39 |
| **P2** | Reader Quarantine Isolation Diagnostic & Cross-Store Contract | PASSED | 1 / 1 |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | PASSED | 5 / 5 |
| **Post**| Database Postflight Integrity Check | PASSED | 1 / 1 |

---

## 3. Профиль производительности (Gate G7)
- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`35.86 ms`**
- **Средняя задержка (CPU)**: **`34.38 ms`**
- **Медиана ($p_{50}$)**: **`34.35 ms`**
- **95-й процентиль ($p_{95}$)**: **`59.38 ms`**
- **99-й процентиль ($p_{99}$)**: **`68.98 ms`**
- **Минимальная задержка**: **`18.72 ms`**
- **Максимальная задержка**: **`71.78 ms`**
- **Суммарное время набора (25 запросов)**: **`0.9 s`**

---

## 4. Сводка выполнения блоков этапа Stage 4.2.8

- **P3 (Shadow Pilot Online Verification & Rejection of False GO)**: Устранены контрпримеры ложного GO; внедрён fail-closed предикат; 12 независимых контрактных сценариев; разделено сырое и нормализованное сравнение полезной нагрузки; проверены счётчики `_executor`; дедлайны реально применены к `_dispatch`; статус `BLOCKED_DEPENDENCY` при отключённом сервисе эмбеддингов.
- **P2 (Quarantine & Reader Protection Truth)**: Диагностический тест доказал возврат чанков из LanceDB при наличии статуса карантина в SQLite; EIG в режиме shadow не фильтрует поисковую выдачу читателю; честно зафиксировано `READ_ISOLATION_NOT_PROVEN`; `CROSS_STORE_RECOVERY: BLOCKED`.
- **M2 (Drive Watcher Delivery Reliability & Reporting Alignment)**: Автоматическая доставка ТЗ Task Scheduler ровно в 12:20:01; безопасный останов `STATE_CORRUPT_HALTED`; восстановление состояния `reconstruct_state_from_artifacts()`; детерминированные ID событий; идемпотентность по хешу; политика повторов согласована с периодическим запуском (`periodic_scheduled_poll`).
- **I3 (LanceDB Canonical Digest & Arrow Scheme Rollback)**: 14 полей схемы Arrow в каноническом дайджесте отката LanceDB; Counter для мультимножеств; детекция подмены провенанса.
- **S5 (Synthetic Retrieval Adapter Benchmark)**: 105 запросов подтверждают 100% побайтную идентичность вывода MCP при среднем оверхеде 0.04 мс.

---

## 5. Оставшиеся дефекты и технические ограничения (Residual Risks)
1. **Недоступность сервиса эмбеддингов**: сервис на порту 8089 отключён (`Socket connection to 127.0.0.1:8089 timed out after 0.5s (TimeoutError: timed out)`). Реальный поиск заблокирован (`BLOCKED_DEPENDENCY`). Требуется запуск оператором: `1. Ensure verified safe/isolated storage environment (OS read-only mode or agreed isolated copy); 2. Launch embedding service (llama-server) on http://127.0.0.1:8089/v1/embeddings with model 'Qwen3-Embedding-0.6B-Q8_0.gguf' (dim=1024).`.
2. **Отсутствие 2PC между SQLite и LanceDB**: при сбое записи в SQLite добавленные векторы в LanceDB не откатываются автоматически (`CROSS_STORE_RECOVERY: BLOCKED`).
3. **Изоляция читателей от карантина не доказана**: прямое векторное чтение LanceDB возвращает чанки изолированных файлов (`READER_QUARANTINE_ISOLATION: READ_ISOLATION_NOT_PROVEN`), поскольку shadow EIG не выполняет активную фильтрацию поисковой выдачи.
4. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`.

---

## 6. Ссылки на подробные технические артефакты
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
- **Матрица тестов (197 проверок)**: [`reports/stage4_2_8_test_matrix.json`](stage4_2_8_test_matrix.json)
- **Отчёт реального пилота поиска**: [`reports/stage4_2_8_real_search_pilot.json`](stage4_2_8_real_search_pilot.json)
- **Протокол контрактных отказов и контрпримеров**: [`reports/stage4_2_8_contract_failures.json`](stage4_2_8_contract_failures.json)
- **Отчёт службы доставки Drive Watcher**: [`reports/stage4_2_8_watcher_delivery.json`](stage4_2_8_watcher_delivery.json)
- **Диагностика изоляции читателей и карантина**: [`reports/stage4_2_8_reader_isolation.json`](stage4_2_8_reader_isolation.json)
- **Доказательства безопасности индексатора**: [`reports/stage4_2_8_indexer_recovery.json`](stage4_2_8_indexer_recovery.json)
- **Провенанс и криптографические контрольные суммы**: [`reports/stage4_2_8_provenance.json`](stage4_2_8_provenance.json)
- **Достоверность первоисточников**: [`reports/stage4_2_8_source_fidelity.json`](stage4_2_8_source_fidelity.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
