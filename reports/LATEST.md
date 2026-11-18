# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.9 — POST-FIX RETRIEVAL EVIDENCE PILOT (ТЗ `FR-TZ-20261118-015` / Редакция 1.2 от 18.11.2026, SHA-256 `dc58fe98eb22fdfb9ae1c4ffb3b8fe7feef364d2931a7f05c6c0e527fcbbfe8d`, 17 234 байта)  
**Статус этапа**: **`WAITING_OPERATOR_SEARCH_APPROVAL` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `HARNESS_FAIL_CLOSED_VERIFIED: YES` / `TEST_SUITE_G15_R12: 10/10 PASS` / `TEST_SUITE_P15: 10/10 PASS` / `REGRESSION_014: 42/42 PASS` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенное предусловие DEP-014**: **`SATISFIED`** (ТЗ-014 закрыто: коммит кода [`af984382c75a9a9844209dab96350e31d39df804`](https://github.com/Kritik35/flying-rag-mcp/commit/af984382c75a9a9844209dab96350e31d39df804), коммит отчёта [`271ec6183601d045b010f544267198f5af3ed2a1`](https://github.com/Kritik35/flying-rag-mcp/commit/271ec6183601d045b010f544267198f5af3ed2a1), тесты: 42/42 PASS в модуле, 73/73 PASS в регрессии)  
**Коммит кода и тестов ТЗ-015 Rev 1.2 (Phase A)**: [`04fe8d22ab4c6e2680a0d345b88b9967dbb8467d`](https://github.com/Kritik35/flying-rag-mcp/commit/04fe8d22ab4c6e2680a0d345b88b9967dbb8467d) (Tree: `c98032ad03e2...`, Parent: `f89477608d7e...`)  
**Родительский коммит отчётов**: [`f89477608d7e46fb331590fa7b2cccb584a5c64f`](https://github.com/Kritik35/flying-rag-mcp/commit/f89477608d7e46fb331590fa7b2cccb584a5c64f) (Tree: `820a80cb66ee...`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый READ-ONLY)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `1794429401.7884293` — строго неизменна)  
**Реальные поисковые вызовы к корпусу для текущей задачи**: **СТРОГО 0** (`actual_corpus_search_calls = 0`)  
**Режим**: STRICT OFFLINE / HARNESS FAIL-CLOSED VERIFICATION / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги реализации и верификации ТЗ-015 Rev 1.2

1. **Устранение замечаний P0-R1 .. P0-R3, P1-Q1**:
   - **P0-R1 (Изоляция сырых текстов)**: CLI stdout/stderr и отчёты Git содержат только проверенные метаданные, SHA-256 и цитаты $\le 200$ символов; сырые результаты сохраняются в temp под уникальным run ID (UUID + timestamp); изоляция маркера `SECRET_FIXTURE_SENTINEL_015` подтверждена.
   - **P0-R2 (Строгая каноническая идентичность рангов)**: `compare_ranks()` переведён на `extract_canonical_id()` и предикат `all()`; дубликаты, псевдо-ID ('None', 'null', '{}') и несоответствия редакций строго отклоняются (`return False`).
   - **P0-R3 (Полная санация окружения)**: Дочернее окружение очищается от ВСЕХ переменных с префиксом `FLYING_RAG_*` перед запуском; `shadow_pilot_worker.py` сбрасывает их на старте; проверено отсутствие внешних записей.
   - **P1-Q1 (Качество нормы vs механический успех)**: Введена функция `evaluate_normative_evidence()` с раздельными метриками (`TARGET_DOC_MATCH`, `TARGET_EDITION_MATCH`, `TARGET_CLAUSE_MATCH`, `HAS_PAGE_OR_VALID_LOCATOR`, `FULL_CLAUSE_EVIDENCE`, `SOURCE_FIDELITY`); счётчик реальных вызовов увеличивается строго после фактического запуска (`spawned=True`).
   - **Архитектура мониторинга**: Штатный 5-минутный опрос `FlyingRAG_Drive_Inbox_Watcher` (Планировщик Windows) сохранён без изменений; 5-секундный демон `watch_drive_tz.py` (task-20723) является вспомогательным сессионным монитором.

2. **Верификация матриц тестов**:
   - `tests/test_postfix_pilot_fail_closed_015_rev1_2.py`: **10/10 PASS** (9.7 с).
   - `tests/test_postfix_pilot_fail_closed_015.py`: **10/10 PASS** (6.7 с).
   - `tests/test_retrieval_clause_edition_014.py`: **42/42 PASS** (47.9 с).

3. **Аудиторские статусы неизменности и готовности**:
   - `ISOLATED_COPY_VERIFIED: YES`
   - `CONSISTENT_SNAPSHOT: UNVERIFIED`
   - `MODEL_INDEX_IDENTITY: UNVERIFIED`
   - `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY`
   - `ACTUAL_CORPUS_SEARCH_CALLS: 0`
   - `STATUS: WAITING_OPERATOR_SEARCH_APPROVAL`

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`STATUS`** | **`WAITING_OPERATOR_SEARCH_APPROVAL`** | Все требования Rev 1.2 выполнены, матрицы G15-R12 (10/10) и P15 (10/10) пройдены, ожидается санкция оператора. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу в рамках подготовки выполнено: строго 0. |
| **`HARNESS_FAIL_CLOSED_VERIFIED`** | **`YES`** | Утечка в stdout закрыта, строгий rank identity подтверждён, очистка окружения завершена. |
| **`TEST_SUITE_G15_R12`** | **`10/10 PASS`** | Все 10 сценариев G15-R12-01..10 успешно проверены без обращения к боевой базе. |
| **`TEST_SUITE_P15_01_10`** | **`10/10 PASS`** | Все 10 сценариев P15-01..P15-10 успешно проверены. |
| **`ISOLATED_COPY_VERIFIED`** | **`YES`** | Изолированная копия проверена через `check_readonly_scope` и `validate_pilot_config`. |
| **`CONSISTENT_SNAPSHOT`** | **`UNVERIFIED`** | Последовательное копирование компонентов в ТЗ-011. |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Совпадение размерности 1024 не доказывает идентичности весов исторического индекса. |
| **`PILOT_NATURE`** | **`DIAGNOSTIC_PILOT_ONLY`** | Сертификация для production заблокирована до подтверждения снимка и модели. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 3. Детальные отчёты этапа

- [POSTFIX_PILOT_READINESS_015.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POSTFIX_PILOT_READINESS_015.md) — подробный отчёт о готовности стенда и решении errata Rev 1.2.
- [postfix_pilot_readiness_015.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/postfix_pilot_readiness_015.json) — структурированные метаданные readiness.
