# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.6 (Доказательная приёмка Stage 4.2.5 и надёжность доставки ТЗ)
**Дата обновления**: 2026-11-16
**Текущая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (tested code commit)**: [`fe00171853557bf5545b5c42d300e720aa052373`](https://github.com/Kritik35/flying-rag-mcp/commit/fe00171853557bf5545b5c42d300e720aa052373)
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Run ID**: `stage4_2_6_20261116_104245_fe001718`
**Tree SHA**: `5e3393bd1c5305eb2e3c4e5a8e4c29b7fbcaa20e`
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH

---

## 1. Официальные вердикты этапа Stage 4.2.6

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`DRIVE_DELIVERY_RELIABILITY`** | **`GO`** | Блок M1 закрыт: автоматическая доставка ТЗ `FR-TZ-20261116-002` Task Scheduler подтверждена в 10:10:00 (SHA256: `a3366066...`, 23 676 байт). Устранена блокировка повторов при неизменном mtime/size, bootstrap при ошибках ставит `BASELINE_UNREADABLE`, состояние перезагружается под локом, повреждённый state архивируется. |
| **`REAL_RETRIEVAL_SHADOW_PILOT`** | **`BLOCKED`** | Блок S6 закрыт: локальный Lemonade embedding server на `localhost:13305` отключён (`[WinError 10061]`). Зафиксирован честный статус `BLOCKED_DEPENDENCY` без подмены выдачи моками или SELECT LIMIT. Уточнено, что 0.11 мс этапа 4.2.5 относились к оверхеду синтетического адаптера. |
| **`VECTOR_ROLLBACK_INTEGRITY`** | **`GO`** | Блок I3 (часть 1) закрыт: `_row_canonical_digest` покрывает все 14 полей схемы Arrow. Мультимножества через Counter выявляют дубликаты. Подмена текста, векторов или метаданных провенанса вызывает `RuntimeError`. |
| **`CROSS_STORE_RECOVERY`** | **`BLOCKED`** | Блок I3 (часть 2) закрыт: распределённый 2PC между SQLite и LanceDB не реализован. Сбой в SQLite изолирует файл статусом карантина, чанки в LanceDB остаются сиротами (orphan), читатели защищены фильтрацией EIG. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Развёртывание на продакшне строго **ЗАПРЕЩЕНО**. Репозиторий production read-only на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 2. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **154**
- **Успешно**: **154** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1,485,103,104 байт, хеш среза и нулевой размер WAL неизменны.
- **Статус рабочей директории**: **Clean (True)** на момент запуска приёмки.

### Результаты по гейтам (Gates G0 — G8, M1, S5, S6)
| Гейт | Название | Статус | Тестов |
|:---|:---|:---:|:---:|
| **G0** | Environment Isolation & Baseline Anchor | PASSED | 6 / 6 |
| **M1** | Google Drive Inbox Watcher Delivery Reliability & Error Recovery | PASSED | 14 / 14 |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity (Arrow Schema Rollback Digest) | PASSED | 33 / 33 |
| **G2** | Multi-chunk Sequential Stitching & Coordinate Invariants | PASSED | 9 / 9 |
| **G3** | Formula & Mathematical Integrity Gate | PASSED | 5 / 5 |
| **G4** | Topic Alignment & Evidence Status Synthesis | PASSED | 15 / 15 |
| **G5** | Document Resolution & Read-only SQLite URI | PASSED | 4 / 4 |
| **G6** | Shadow Adapter Safety, Congruence & MCP Path Isolation | PASSED | 35 / 35 |
| **G7** | Adversarial Test Suite & Latency Distribution | PASSED | 25 / 25 |
| **S5** | Synthetic Retrieval Adapter Benchmark (105 Queries) | PASSED | 1 / 1 |
| **S6** | Real Retrieval Shadow Pilot (Section 3.3) | PASSED | 1 / 1 |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | PASSED | 5 / 5 |
| **Post**| Database Postflight Integrity Check | PASSED | 1 / 1 |

---

## 3. Профиль производительности (Gate G7)
- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`42.3 ms`**
- **Средняя задержка (CPU)**: **`31.25 ms`**
- **Медиана ($p_{50}$)**: **`34.64 ms`**
- **95-й процентиль ($p_{95}$)**: **`69.51 ms`**
- **99-й процентиль ($p_{99}$)**: **`98.03 ms`**
- **Минимальная задержка**: **`19.67 ms`**
- **Максимальная задержка**: **`107.0 ms`**
- **Суммарное время набора (25 запросов)**: **`1.06 s`**

---

## 4. Сводка выполнения блоков этапа Stage 4.2.6

- **M1 (Drive Watcher Delivery Reliability)**: Автоматическая доставка ТЗ подтверждена Task Scheduler; исправлены повторные попытки при неизменном mtime; bootstrap изолирует нечитаемые файлы в BASELINE_UNREADABLE; состояние перезагружается внутри критической секции под msvcrt.locking; невалидный JSON архивируется без перезаписи.
- **S6 (Real Retrieval Shadow Pilot)**: Реальный поиск search_documents() честно фиксирует отключённый бэкенд Lemonade (localhost:13305) со статусом BLOCKED_DEPENDENCY; категорически исключены моки и пустые выдачи.
- **I3 (LanceDB Canonical Digest & Cross-Store Failure Window)**: Полный охват 14 полей Arrow в дайджесте отката LanceDB; Counter для мультимножеств; детекция подмены провенанса; контракт окна сбоя хранилищ (quarantine в SQLite, orphan в LanceDB, EIG read-side filtering).
- **S5 (Synthetic Retrieval Adapter Benchmark)**: 105 запросов подтверждают 100% побайтную идентичность вывода MCP при среднем оверхеде 0.04 мс.

---

## 5. Оставшиеся дефекты и технические ограничения (Residual Risks)
1. **Недоступность Lemonade Embedding Server**: локальный сервис на `localhost:13305` отключён (`[WinError 10061]`). Реальный поиск заблокирован (`BLOCKED_DEPENDENCY`).
2. **Отсутствие 2PC между SQLite и LanceDB**: при сбое записи в SQLite добавленные векторы в LanceDB не откатываются автоматически, изолируясь на уровне EIG.
3. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`.

---

## 6. Ссылки на подробные технические артефакты
- **Полный отчёт приёмки Stage 4.2.6**: [`reports/STAGE4_2_6_ACCEPTANCE.md`](STAGE4_2_6_ACCEPTANCE.md)
- **Машинно-читаемые результаты гейтов**: [`reports/stage4_2_6_gate_results.json`](stage4_2_6_gate_results.json)
- **Матрица тестов (154 проверок)**: [`reports/stage4_2_6_test_matrix.json`](stage4_2_6_test_matrix.json)
- **Отчёт службы доставки Drive Watcher**: [`reports/stage4_2_6_watcher_delivery.json`](stage4_2_6_watcher_delivery.json)
- **Отчёт реального пилота поиска**: [`reports/stage4_2_6_real_search_pilot.json`](stage4_2_6_real_search_pilot.json)
- **Доказательства безопасности индексатора**: [`reports/stage4_2_6_indexer_recovery.json`](stage4_2_6_indexer_recovery.json)
- **Провенанс и криптографические контрольные суммы**: [`reports/stage4_2_6_provenance.json`](stage4_2_6_provenance.json)
- **Достоверность первоисточников**: [`reports/stage4_2_6_source_fidelity.json`](stage4_2_6_source_fidelity.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
