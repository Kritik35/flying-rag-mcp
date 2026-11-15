# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.4 (Shadow Operational Readiness & Indexer Safety Verification)
**Дата обновления**: 2026-11-15
**Текущая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (tested code commit)**: [`4cc4a9027f1590514d7d233885124c8216da4ab3`](https://github.com/Kritik35/flying-rag-mcp/commit/4cc4a9027f1590514d7d233885124c8216da4ab3)
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Run ID**: `stage4_2_4_20261115_223120_4cc4a902`
**Tree SHA**: `cbb02d9b6c46b0d17594d0e3f13dc3276ddf55e1`
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX

---

## 1. Официальные вердикты этапа Stage 4.2.4

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`SHADOW_TRIAL_READY`** | **`GO`** | Блоки S1–S4 полностью закрыты. Bounded shutdown (с таймаутом и честной декларацией `HARD_STOP_UNSUPPORTED`), внешний control file kill-switch с межпроцессным переключением, защита от ложных `USABLE_FOR_ANSWER` при запросах формул, строгие инварианты счётчиков очереди, побайтная идентичность сериализации всех 4 форм выдачи MCP, оверхед диспетчеризации < 25 мс (факт 0.12 мс при искусственной задержке EIG 300 мс). |
| **`INDEXER_SAFETY`** | **`GO`** | Блок I1 полностью закрыт. На реальной таблице LanceDB подтверждено поэлементное восстановление всех полей и float16 векторов (`assert_allclose`, rtol/atol=1e-3) после отката. Префлайт-валидация блокирует некорректные данные до касания диска. Подтверждена идемпотентность повторной индексации. База данных production не затронута. |

---

## 2. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **131**
- **Успешно**: **131** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1 485 103 104 байт, хеш среза и нулевой размер WAL неизменны.
- **Статус рабочей директории**: **Clean (True)** на момент запуска приёмки.

### Результаты по гейтам (Gates G0 — G8)
| Гейт | Название | Статус | Тестов |
|:---|:---|:---:|:---:|
| **G0** | Environment Isolation & Baseline Anchor | PASSED | 6 / 6 |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity | PASSED | 32 / 32 |
| **G2** | Multi-chunk Sequential Stitching & Coordinate Invariants | PASSED | 9 / 9 |
| **G3** | Formula & Mathematical Integrity Gate | PASSED | 5 / 5 |
| **G4** | Topic Alignment & Evidence Status Synthesis | PASSED | 15 / 15 |
| **G5** | Document Resolution & Read-only SQLite URI | PASSED | 4 / 4 |
| **G6** | Shadow Adapter Safety, Congruence & MCP Path Isolation | PASSED | 32 / 32 |
| **G7** | Adversarial Test Suite & Latency Distribution | PASSED | 25 / 25 |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | PASSED | 5 / 5 |
| **Post**| Database Postflight Integrity Check | PASSED | 1 / 1 |

---

## 3. Профиль производительности (Gate G7)
- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`35.33 ms`**
- **Средняя задержка (CPU)**: **`33.75 ms`**
- **Медиана ($p_{50}$)**: **`32.29 ms`**
- **95-й процентиль ($p_{95}$)**: **`50.71 ms`**
- **99-й процентиль ($p_{99}$)**: **`55.87 ms`**
- **Минимальная задержка**: **`21.45 ms`**
- **Максимальная задержка**: **`57.49 ms`**
- **Суммарное время набора (25 запросов)**: **`883.15 ms`**

---

## 4. Сводка выполнения блоков эксплуатационной готовности

- **S1 (Lifecycle & Bounded Shutdown)**: Разделены `stop_accepting()` и `cancel_pending()`, исключено зависание очереди; bounded shutdown с таймаутом через `concurrent.futures.wait`; вызов интегрирован в секцию `finally:` в `rag_server/server.py:run()`; честное декларирование `HARD_STOP_UNSUPPORTED` при зависании фоновых потоков Python.
- **S2 (External Control File Kill-Switch)**: Реализована атомарная запись/замена внешнего JSON-файла управления; при повреждении или отсутствии файла статус безопасно переходит в `disabled` (fail-safe); обеспечено межпроцессное динамическое переключение без изменения env и без перезапуска процесса MCP.
- **S3 (Formula Semantics & EIG Synthesis)**: Реализован парсер формульных запросов (`is_formula_seeking_query`); при отсутствии проверенного математического выражения статус для формульных запросов понижается с ложного `USABLE_FOR_ANSWER` до `EVIDENCE_PARTIAL`; для чисто текстовых запросов сохраняется `USABLE_FOR_ANSWER`.
- **S4 (Async Queue, Multi-Threading & Dispatch Overhead)**: Подтверждены строгие инварианты счётчиков очереди при конкурентной нагрузке; учёт `drop_count`; доказана побайтная идентичность вывода MCP на 4 типах полезной нагрузки; средний оверхед диспетчеризации составляет **0.12 мс** (< 25 мс) при задержке EIG 300 мс.
- **I1 (LanceDB Deep Rollback Verification)**: На реальной таблице LanceDB подтверждено восстановление всех полей (`chunk_id`, `doc_id`, `text`, `text_hash`, `metadata`, `vector`) и численное совпадение float16 векторов (`assert_allclose`, rtol/atol=1e-3); подтверждена защита от NaN/Inf/дубликатов до касания диска и идемпотентность повторной индексации.

---

## 5. Оставшиеся дефекты и технические ограничения (Residual Risks)
1. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, из-за чего в базе сохраняется только метка `(А.3)` без тела формулы. EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`. Устранение требует доработки парсера и полного переиндексирования корпуса (в будущих релизах при снятии запрета NO REINDEX).
2. **Неопределённость редакции без указания года**: Запросы без указания года нормативного документа (например, «СП 60.13330 п. 7.1.1») классифицируются как `AMBIGUOUS_SOURCE` -> `REFUSAL_REQUIRED`.
3. **Физическая недоступность диска H:**: Оригинальные файлы на несмонтированном диске H: помечаются как `SOURCE_NOT_VERIFIED (BLOCKED_BY_SOURCE_UNAVAILABLE)`.

---

## 6. Ссылки на подробные технические артефакты
- **Полный отчёт приёмки Stage 4.2.4**: [`reports/STAGE4_2_4_ACCEPTANCE.md`](STAGE4_2_4_ACCEPTANCE.md)
- **Машинно-читаемые результаты гейтов**: [`reports/stage4_2_4_gate_results.json`](stage4_2_4_gate_results.json)
- **Матрица тестов (131 проверка)**: [`reports/stage4_2_4_test_matrix.json`](stage4_2_4_test_matrix.json)
- **Метрики готовности Shadow**: [`reports/stage4_2_4_shadow_metrics.json`](stage4_2_4_shadow_metrics.json)
- **Доказательства безопасности индексатора**: [`reports/stage4_2_4_recovery.json`](stage4_2_4_recovery.json)
- **Провенанс и криптографические контрольные суммы**: [`reports/stage4_2_4_provenance.json`](stage4_2_4_provenance.json)
- **Достоверность первоисточников**: [`reports/stage4_2_4_source_fidelity.json`](stage4_2_4_source_fidelity.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
