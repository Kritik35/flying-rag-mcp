# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.3 (Reviewer Blockers CR-01–CR-07 Resolution & Verified Attestation)
**Дата обновления**: 2026-11-15
**Текущая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (tested code commit)**: [`e126f1cc9064abb455cd5e065d726eb168388fa2`](https://github.com/Kritik35/flying-rag-mcp/commit/e126f1cc9064abb455cd5e065d726eb168388fa2)
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Run ID**: `stage4_2_2_20261115_213530_e126f1cc`
**Tree SHA**: `99c6a5a0dd98ecbe713956b8b19802c93cec06eb`
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX

---

## 1. Сводка результатов тестирования

- **Общий статус приёмки**: **PASSED**
- **Всего выполненных тестов**: **116**
- **Успешно**: **116** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1 485 103 104 байт, хеш среза и нулевой размер WAL неизменны.

### Результаты по гейтам (Gates G0 — G8)
| Гейт | Название | Статус | Тестов |
|:---|:---|:---:|:---:|
| **G0** | Environment Isolation & Baseline Anchor | PASSED | 6 / 6 |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity | PASSED | 27 / 27 |
| **G2** | Multi-chunk Sequential Stitching & Coordinate Invariants | PASSED | 9 / 9 |
| **G3** | Formula & Mathematical Integrity Gate | PASSED | 5 / 5 |
| **G4** | Topic Alignment & Evidence Status Synthesis | PASSED | 12 / 12 |
| **G5** | Document Resolution & Read-only SQLite URI | PASSED | 4 / 4 |
| **G6** | Shadow Adapter Safety, Congruence & MCP Path Isolation | PASSED | 22 / 22 |
| **G7** | Adversarial Test Suite & Latency Distribution | PASSED | 25 / 25 |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | PASSED | 5 / 5 |
| **Post**| Database Postflight Integrity Check | PASSED | 1 / 1 |

---

## 2. Профиль производительности (Gate G7)
- **Средняя задержка (Wall-Clock)**: **`36.25 ms`**
- **Средняя задержка (CPU)**: **`35.00 ms`**
- **Медиана ($p_{50}$)**: **`31.29 ms`**
- **95-й процентиль ($p_{95}$)**: **`53.02 ms`**
- **99-й процентиль ($p_{99}$)**: **`105.11 ms`**
- **Минимальная задержка**: **`19.53 ms`**
- **Максимальная задержка**: **`121.52 ms`**
- **Суммарное время набора (25 запросов)**: **`906.32 ms`**

---

## 3. Статус закрытия блокеров рецензента (CR-01 — CR-07)
- **CR-01 (P0)**: В `storage/vector_store.py:upsert_chunks()` добавлена обязательная очистка частично добавленных записей перед откатом, верификация числа строк после отката к снапшоту, устранено замалчивание ошибок `except Exception: pass` при multi-doc delete rollback. Добавлено 5 тестов в `tests/test_upsert_atomic_recovery.py`. — **ЗАКРЫТ**
- **CR-02 (P0)**: Реализована `atomic_replace_parent_chunks_and_cache()` в `storage/metadata_db.py`, выполняющая замену parent chunks и обновление cache в одной SQLite-транзакции. Заменены последовательные автокоммиты в `indexer.py`. Добавлены тесты с триггерами в `tests/test_indexer_quarantine_reprocess.py`. — **ЗАКРЫТ**
- **CR-03 (P1/Security)**: Политика по умолчанию: `query_sanitized` исключён из телеметрии (логируются только `query_hash` и длина). Включение сырого текста только через явный опт-ин `FLYING_RAG_SHADOW_LOG_QUERY_TEXT=1`. Усилена санитизация путей (UNC, кавычки с пробелами, русские папки с пробелами, динамическое имя пользователя). — **ЗАКРЫТ**
- **CR-04 (P1)**: Добавлен таймаут `timeout=5.0` в `self._executor.shutdown(wait=wait, timeout=timeout, cancel_futures=True)` с обработкой `TimeoutError`. — **ЗАКРЫТ**
- **CR-05 (P1)**: В `test_shadow_adapter_async_non_blocking` задействован реальный `EvidenceGateResult` и добавлены утверждения `divergence != 'SHADOW_ERROR'`, `divergence == 'CONGRUENT'`, `error_count == 0`. — **ЗАКРЫТ**
- **CR-06 (P1)**: Реализован протокол двухфазного коммита. Тесты запускаются на зафиксированном коммите кода `e126f1cc9064abb455cd5e065d726eb168388fa2`. Все JSON-артефакты содержат поля `tested_commit_sha`, `tested_tree_sha`, `working_tree_sha`. — **ЗАКРЫТ**
- **CR-07 (P1)**: Заменено независимое пересечение множеств на похитовое сравнение (pairwise hit matching) в `rag_server/shadow_eig.py`: совпадение `parent_id` и `source_path` требуется на одном и том же элементе выдачи. Исключена ложная конгруэнтность кросс-хитов. — **ЗАКРЫТ**

---

## 4. Оставшиеся дефекты и технические ограничения (Residual Risks)
1. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, из-за чего в базе сохраняется только метка `(А.3)` без тела формулы. EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`. Устранение требует доработки парсера и полного переиндексирования корпуса (в будущих релизах при снятии запрета NO REINDEX).
2. **Неопределённость редакции без указания года**: Запросы без указания года нормативного документа (например, «СП 60.13330 п. 7.1.1») классифицируются как `AMBIGUOUS_SOURCE` -> `REFUSAL_REQUIRED`.
3. **Физическая недоступность диска H:**: Оригинальные файлы на несмонтированном диске H: помечаются как `SOURCE_NOT_VERIFIED (BLOCKED_BY_SOURCE_UNAVAILABLE)`.

---

## 5. Ссылки на подробные технические артефакты
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
- **Полный отчёт приёмки**: [`reports/STAGE4_2_INDEPENDENT_ACCEPTANCE.md`](STAGE4_2_INDEPENDENT_ACCEPTANCE.md)
- **Машинно-читаемые результаты гейтов**: [`reports/stage4_2_gate_results.json`](stage4_2_gate_results.json)
- **Матрица тестов (116 проверок)**: [`reports/stage4_2_test_matrix.json`](stage4_2_test_matrix.json)
- **Достоверность первоисточников**: [`reports/stage4_2_source_fidelity.json`](stage4_2_source_fidelity.json)
- **Метрики производительности теневого адаптера**: [`reports/stage4_2_shadow_metrics.json`](stage4_2_shadow_metrics.json)
- **Манифест изменений Git**: [`reports/stage4_2_git_manifest.md`](stage4_2_git_manifest.md)
- **Анализ рисков и план отката**: [`reports/STAGE4_2_OPEN_RISKS.md`](STAGE4_2_OPEN_RISKS.md)
