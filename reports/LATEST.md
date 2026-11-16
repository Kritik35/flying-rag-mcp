# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.5 (Google Drive Inbox Bootstrap + Controlled Shadow Pilot)
**Дата обновления**: 2026-11-16
**Текущая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (tested code commit)**: [`74c0ade8608da33c5ee0debf5c930597d0af5a2e`](https://github.com/Kritik35/flying-rag-mcp/commit/74c0ade8608da33c5ee0debf5c930597d0af5a2e)
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Run ID**: `stage4_2_5_20261116_095827_74c0ade8`
**Tree SHA**: `2110a754ab12aa9af6e2084abfc096a6cdf319f0`
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX

---

## 1. Официальные вердикты этапа Stage 4.2.5

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`DRIVE_MONITOR`** | **`MONITOR_READY_DETECTION_ONLY`** | Блок M0 закрыт. Мониторинг Google Drive Inbox (`G:\Мой диск\FlyingRAG_TZ_Inbox`) развёрнут через Windows Task Scheduler (`FlyingRAG_Drive_Inbox_Watcher`, интервал 5 мин). Кросс-процессный мьютекс `msvcrt.locking` исключает параллельные запуски. Файлы `.gdoc`/`.gsheet` безопасно пропускаются. Базовый bootstrap зафиксировал существующий файл ТЗ в статусе `ACKNOWLEDGED`. Режим строго `DETECTION_ONLY`. |
| **`SHADOW_TRIAL_READY`** | **`GO`** | Блоки S1–S5 закрыты. Детерминированное разрешение путей control_file от корня приложения исключает зависимость от CWD. Fail-safe при отсутствии файла отключает адаптер. В бенчмарке из 105 запросов подтверждены 100% побайтная идентичность вывода MCP и сохранение ранжирования при среднем оверхеде 0.11 мс ($p_{50}=0.06 мс, p_{95}=0.21 мс, 0 сбоев). |
| **`INDEXER_ISOLATED_SAFETY`** | **`GO`** | Блоки I1–I2 закрыты. Глубокая проверка отката LanceDB проверяет канонический дайджест каждой строки (`chunk_id`, `doc_id`, `text`, `text_hash`, `metadata`, `vector.tobytes()`). Любая подмена данных вызывает `RuntimeError`. Проверен контракт согласованности окон сбоев между SQLite и LanceDB. База production не затронута. |

---

## 2. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **145**
- **Успешно**: **145** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1,485,103,104 байт, хеш среза и нулевой размер WAL неизменны.
- **Статус рабочей директории**: **Clean (True)** на момент запуска приёмки.

### Результаты по гейтам (Gates G0 — G8, M0, S5)
| Гейт | Название | Статус | Тестов |
|:---|:---|:---:|:---:|
| **G0** | Environment Isolation & Baseline Anchor | PASSED | 6 / 6 |
| **M0** | Google Drive Inbox Watcher & Bootstrap | PASSED | 8 / 8 |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity | PASSED | 31 / 31 |
| **G2** | Multi-chunk Sequential Stitching & Coordinate Invariants | PASSED | 9 / 9 |
| **G3** | Formula & Mathematical Integrity Gate | PASSED | 5 / 5 |
| **G4** | Topic Alignment & Evidence Status Synthesis | PASSED | 15 / 15 |
| **G5** | Document Resolution & Read-only SQLite URI | PASSED | 4 / 4 |
| **G6** | Shadow Adapter Safety, Congruence & MCP Path Isolation | PASSED | 35 / 35 |
| **G7** | Adversarial Test Suite & Latency Distribution | PASSED | 25 / 25 |
| **S5** | Shadow Pilot 105-Query Paired-Delta Benchmark | PASSED | 1 / 1 |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | PASSED | 5 / 5 |
| **Post**| Database Postflight Integrity Check | PASSED | 1 / 1 |

---

## 3. Профиль производительности (Gate G7)
- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`41.03 ms`**
- **Средняя задержка (CPU)**: **`36.88 ms`**
- **Медиана ($p_{50}$)**: **`35.53 ms`**
- **95-й процентиль ($p_{95}$)**: **`57.95 ms`**
- **99-й процентиль ($p_{99}$)**: **`59.72 ms`**
- **Минимальная задержка**: **`27.42 ms`**
- **Максимальная задержка**: **`60.06 ms`**
- **Суммарное время набора (25 запросов)**: **`1.03 s`**

---

## 4. Сводка выполнения блоков эксплуатационной готовности

- **M0 (Drive Inbox Watcher & Bootstrap)**: Мониторинг Google Drive развёрнут в режиме `DETECTION_ONLY`; межпроцессный лок `msvcrt.locking`; безопасный пропуск виртуальных `.gdoc` DriveFS; существующее ТЗ зафиксировано в baseline без лишних событий; Task Scheduler зарегистрирован на 5 минут.
- **S5 (Shadow Path Hardening & 105-Query Benchmark)**: Относительный путь к `control_file` привязан к `(ROOT / ctrl_file_path).resolve()` независимо от CWD; fail-safe disabled при отсутствии файла; 105 запросов показали 100% побайтную идентичность MCP и сохранение рангов при среднем оверхеде 0.11 мс.
- **I2 (Indexer Deep Digest & Failure Reconciliation)**: Откат LanceDB проверяет канонический дайджест каждой строки включая float32 байты векторов; подмена текста/вектора вызывает аварийный останов; проверена атомарность согласования окон сбоев между хранилищами SQLite и LanceDB.
- **S1–S4 (Operational Core)**: Bounded shutdown с таймаутом и статусом `HARD_STOP_UNSUPPORTED`, внешний файл управления kill-switch, детекция формульных запросов с понижением статуса, инварианты счётчиков очереди.

---

## 5. Оставшиеся дефекты и технические ограничения (Residual Risks)
1. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, из-за чего в базе сохраняется только метка `(А.3)` без тела формулы. EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`. Устранение требует доработки парсера и полного переиндексирования корпуса (в будущих релизах при снятии запрета NO REINDEX).
2. **Неопределённость редакции без указания года**: Запросы без указания года нормативного документа (например, «СП 60.13330 п. 7.1.1») классифицируются как `AMBIGUOUS_SOURCE` -> `REFUSAL_REQUIRED`.
3. **Физическая недоступность диска H:**: Оригинальные файлы на несмонтированном диске H: помечаются как `SOURCE_NOT_VERIFIED (BLOCKED_BY_SOURCE_UNAVAILABLE)`.

---

## 6. Ссылки на подробные технические артефакты
- **Полный отчёт приёмки Stage 4.2.5**: [`reports/STAGE4_2_5_ACCEPTANCE.md`](STAGE4_2_5_ACCEPTANCE.md)
- **Машинно-читаемые результаты гейтов**: [`reports/stage4_2_5_gate_results.json`](stage4_2_5_gate_results.json)
- **Матрица тестов (145 проверок)**: [`reports/stage4_2_5_test_matrix.json`](stage4_2_5_test_matrix.json)
- **Отчёт службы мониторинга Drive**: [`reports/stage4_2_5_drive_watcher.json`](stage4_2_5_drive_watcher.json)
- **Метрики бенчмарка Shadow Pilot**: [`reports/stage4_2_5_shadow_pilot.json`](stage4_2_5_shadow_pilot.json)
- **Доказательства безопасности индексатора**: [`reports/stage4_2_5_indexer_recovery.json`](stage4_2_5_indexer_recovery.json)
- **Провенанс и криптографические контрольные суммы**: [`reports/stage4_2_5_provenance.json`](stage4_2_5_provenance.json)
- **Достоверность первоисточников**: [`reports/stage4_2_5_source_fidelity.json`](stage4_2_5_source_fidelity.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
