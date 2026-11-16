# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.7 (Настоящий ON/OFF-пилот, честная изоляция читателей и завершение проверок Stage 4.2.6)
**Дата обновления**: 2026-11-16
**Текущая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (tested code commit)**: [`b4e33be4bfb632b63108a6bfb1364f1531f28da9`](https://github.com/Kritik35/flying-rag-mcp/commit/b4e33be4bfb632b63108a6bfb1364f1531f28da9)
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Run ID**: `stage4_2_7_20261116_114346_b4e33be4`
**Tree SHA**: `66ddf0299f822c73e034e15facf088a61969bc43`
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH

---

## 1. Официальные вердикты этапа Stage 4.2.7

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`DRIVE_DELIVERY_RELIABILITY`** | **`GO`** | Блок M2 закрыт: автоматическая доставка ТЗ `FR-TZ-20261116-003` Task Scheduler подтверждена в 11:00:00 (SHA256: `21b452ef...`, 18 178 байт). Реализована защита от повреждения `state.json` (безопасный останов `STATE_CORRUPT_HALTED`), восстановление состояния `reconstruct_state_from_artifacts()`, детерминированный ID события, идемпотентность по SHA256 и персистентный лимит повторов `FAILED_PERMANENT` (5 попыток). |
| **`REAL_RETRIEVAL_SHADOW_PILOT`** | **`BLOCKED`** | Блок P1 закрыт: реализован истинный парный контракт OFF (`FLYING_RAG_SHADOW_EIG=0`) vs ON (`FLYING_RAG_SHADOW_EIG=1`) через реальный диспетчер `_dispatch`, проверка вызова наблюдателя с `request_id`, честный компаратор рангов, дедлайн 2.0s / 5.0s через daemon-поток без зависаний. Зафиксирован честный статус `BLOCKED_DEPENDENCY` при недоступности Lemonade embedding сервера (`http://localhost:13305/api/v1/embeddings`, `[WinError 10061]`). |
| **`VECTOR_ROLLBACK_INTEGRITY`** | **`GO`** | Канонический дайджест всех 14 полей Arrow, сверка мультимножеств векторов и строк, защита от подмены провенанса. |
| **`CROSS_STORE_RECOVERY`** | **`BLOCKED`** | Распределённый 2PC между SQLite и LanceDB отсутствует. При сбое индексации SQLite помечает файл как `quarantine_failed_indexing`, но в LanceDB остаются orphan-векторы. Автоматический межбазовый откат не производится. |
| **`READER_QUARANTINE_ISOLATION`** | **`READ_ISOLATION_NOT_PROVEN`** | Блок P2 закрыт: прямое чтение LanceDB возвращает чанки документов, находящихся в карантине SQLite. EIG в режиме shadow выполняет лишь асинхронное фоновое наблюдение (`observe_async`) и НЕ фильтрует поисковую выдачу пользователю. Изоляция читателей не доказана. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Развёртывание на продакшне строго **ЗАПРЕЩЕНО**. Baseline production `9b498bf5dc09e964d035049a53582d52f13cdc95` остаётся неизменным. |

---

## 2. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **163**
- **Успешно**: **163** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1,485,103,104 байт, хеш среза и нулевой размер WAL неизменны.
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
| **S6** | Real Retrieval Shadow Pilot (Section 3.3 / Block P1) | PASSED | 5 / 5 |
| **P2** | Reader Quarantine Isolation Diagnostic & Cross-Store Contract | PASSED | 1 / 1 |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | PASSED | 5 / 5 |
| **Post**| Database Postflight Integrity Check | PASSED | 1 / 1 |

---

## 3. Профиль производительности (Gate G7)
- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`51.77 ms`**
- **Средняя задержка (CPU)**: **`41.88 ms`**
- **Медиана ($p_{50}$)**: **`49.28 ms`**
- **95-й процентиль ($p_{95}$)**: **`89.28 ms`**
- **99-й процентиль ($p_{99}$)**: **`100.25 ms`**
- **Минимальная задержка**: **`23.52 ms`**
- **Максимальная задержка**: **`102.55 ms`**
- **Суммарное время набора (25 запросов)**: **`1.29 s`**

---

## 4. Сводка выполнения блоков этапа Stage 4.2.7

- **P1 (Real Shadow Pilot Online/Offline Contract)**: Настоящий парный запуск OFF vs ON через `_dispatch`; валидация наблюдателя с `request_id`; честный компаратор рангов и пейлоадов; строгие неблокирующие дедлайны (2.0s / 5.0s); статус `BLOCKED_DEPENDENCY` при отключённом сервисе Lemonade.
- **P2 (Quarantine & Reader Protection Truth)**: Диагностический тест доказал возврат чанков из LanceDB при наличии статуса карантина в SQLite; EIG в режиме shadow не фильтрует поисковую выдачу читателю; честно зафиксировано `READ_ISOLATION_NOT_PROVEN`; `CROSS_STORE_RECOVERY: BLOCKED`.
- **M2 (Drive Watcher Crash Recovery & Idempotency)**: Автоматическая доставка ТЗ Task Scheduler ровно в 11:00:00; безопасный останов `STATE_CORRUPT_HALTED` при повреждении `state.json`; восстановление состояния `reconstruct_state_from_artifacts()`; детерминированные ID событий; идемпотентность по хешу; персистентный лимит повторов до 5 попыток.
- **I3 (LanceDB Canonical Digest & Arrow Scheme Rollback)**: 14 полей схемы Arrow в каноническом дайджесте отката LanceDB; Counter для мультимножеств; детекция подмены провенанса.
- **S5 (Synthetic Retrieval Adapter Benchmark)**: 105 запросов подтверждают 100% побайтную идентичность вывода MCP при среднем оверхеде 0.22 мс.

---

## 5. Оставшиеся дефекты и технические ограничения (Residual Risks)
1. **Недоступность Lemonade Embedding Server**: локальный сервис на `localhost:13305` отключён (`[WinError 10061]`). Реальный поиск заблокирован (`BLOCKED_DEPENDENCY`). Требуется запуск оператором перед включением пилота.
2. **Отсутствие 2PC между SQLite и LanceDB**: при сбое записи в SQLite добавленные векторы в LanceDB не откатываются автоматически (`CROSS_STORE_RECOVERY: BLOCKED`).
3. **Изоляция читателей от карантина не доказана**: прямое векторное чтение LanceDB возвращает чанки изолированных файлов (`READER_QUARANTINE_ISOLATION: READ_ISOLATION_NOT_PROVEN`), поскольку shadow EIG не выполняет активную фильтрацию поисковой выдачи.
4. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`.

---

## 6. Ссылки на подробные технические артефакты
- **Полный отчёт приёмки Stage 4.2.7**: [`reports/STAGE4_2_7_ACCEPTANCE.md`](STAGE4_2_7_ACCEPTANCE.md)
- **Машинно-читаемые результаты гейтов**: [`reports/stage4_2_7_gate_results.json`](stage4_2_7_gate_results.json)
- **Матрица тестов (163 проверок)**: [`reports/stage4_2_7_test_matrix.json`](stage4_2_7_test_matrix.json)
- **Отчёт службы доставки Drive Watcher**: [`reports/stage4_2_7_watcher_delivery.json`](stage4_2_7_watcher_delivery.json)
- **Отчёт реального пилота поиска**: [`reports/stage4_2_7_real_search_pilot.json`](stage4_2_7_real_search_pilot.json)
- **Диагностика изоляции читателей и карантина**: [`reports/stage4_2_7_reader_isolation.json`](stage4_2_7_reader_isolation.json)
- **Доказательства безопасности индексатора**: [`reports/stage4_2_7_indexer_recovery.json`](stage4_2_7_indexer_recovery.json)
- **Провенанс и криптографические контрольные суммы**: [`reports/stage4_2_7_provenance.json`](stage4_2_7_provenance.json)
- **Достоверность первоисточников**: [`reports/stage4_2_7_source_fidelity.json`](stage4_2_7_source_fidelity.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
