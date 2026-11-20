# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.11 — POST-PILOT NORMATIVE CLAUSE RECONSTRUCTION (ТЗ `FR-TZ-20261119-017` Rev 1.0 от 19.11.2026, SHA-256 `9f4715ff33e53e934bd4f789aa02aa4af8567d43a6c990a573105f480af45ee5`, 15 883 байта)  
**Статус этапа**: **`CODE_GATE: GO_WITH_OFFLINE_SCOPE` / `CACHE_ROTATION_INTEGRATED: YES` / `ENR_ATTRIBUTION_SEPARATED: YES` / `TEST_SUITE_C17: 12/12 PASS` / `CACHE_REVISION_SUITE: 2/2 PASS` / `TOTAL_TESTS_PASS: 84/84 PASS` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенное предусловие DEP-016**: **`SATISFIED`** (ТЗ-016 закрыто: коммит отчёта [`210da126931da555cb70159391a681b613ba6b7e`](https://github.com/Kritik35/flying-rag-mcp/commit/210da126931da555cb70159391a681b613ba6b7e), 6 реальных вызовов выполнены в строгом соответствии с санкцией)  
**Интегрированный коммит PR № 1**: [`2600c04b75c887da4c482f8140d6d87920601f02`](https://github.com/Kritik35/flying-rag-mcp/commit/2600c04b75c887da4c482f8140d6d87920601f02)  
**Коммит проверенного кода (Phase A)**: [`bce9665aee0ea1aaf2a1acfd632cd7390cfd8598`](https://github.com/Kritik35/flying-rag-mcp/commit/bce9665aee0ea1aaf2a1acfd632cd7390cfd8598)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый READ-ONLY)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `11.11.2026 23:36:41` — строго неизменна)  
**Реальные поисковые вызовы к корпусу для текущей задачи**: **СТРОГО 0** (`actual_corpus_search_calls = 0`)  
**Режим**: STRICT OFFLINE / READ-ONLY FORENSIC & CACHE ROTATION / ENR ATTRIBUTION REVISION / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги реализации и верификации ТЗ-017

1. **Судебно-техническая экспертиза `search_cache` (причина дефекта ТЗ-016)**:
   - В таблице `search_cache` изолированной SQLite найдены записи с ID 976, 977, 978, созданные **17.11.2026** в рамках ТЗ-011 со скоупом `retrieval-quality-v10-enr`.
   - Временные метки `last_hit_at` записей соответствуют времени запусков ТЗ-016 (**19.11.2026 22:14:35, 22:14:56, 22:15:36**).
   - Полезная нагрузка всех 6 вызовов ТЗ-016 на 100% совпала с содержимым этих исторических строк (`FULL PAYLOAD IDENTICAL: True`). Из-за перехвата в `SemanticCache.lookup_exact()` актуальный код извлечения норм во время поиска ТЗ-016 не вызывался.

2. **Прямое тестирование `NormRegistry` на изолированном корпусе (без поиска)**:
   - Прямой вызов `extract_clause_from_doc()` показал восстановление границ Q004 и Q088-2020; для Q010 сшивка выполнена, но итоговый статус остаётся `context_partial` (полнота не доказана):
     - **СП 7 п. 6.4**: заголовок на месте, чанки 0017+0018 сшиты (`status=context_sufficient`).
     - **СП 7 п. 6.10**: чанки 0021+0022 сшиты (3 758 симв.), в тексте присутствуют **EI 30** и **EI 15**, но `context_partial` — подтверждённый структурный конец пункта не установлен; `FULL_CLAUSE_EVIDENCE` не повышать до PASS.
     - **СП 60 п. 7.1.1**: текст извлечён чисто, хвост п. 6.4.14 отсечён (`status=context_sufficient`).
   - Переписывать алгоритм сшивки в `NormRegistry` не требовалось.

3. **Интеграция PR № 1 (Ротация ключа кэша)**:
   - Строковый токен контракта скоупа в `rag_server/tools.py` обновлён с `"retrieval-quality-v10-enr"` на `"retrieval-quality-v11-enr-clause-boundary"`.
   - Старый кэш v10 игнорируется поисковым движком при любых последующих вызовах без модификации и удаления исторических записей.
   - Тесты `test_retrieval_cache_revision_017.py`: **2/2 PASS**.

4. **Разделение атрибуции ENR (Требование C17-09)**:
   - Синтетические пункты нормативного поиска (ENR) отделены от физических векторных чанков:
     - `retrieval_origin = "ENR_DERIVED_CLAUSE"`
     - `derived_clause_id = f"clause_{clause_num}"`
     - `physical_parent_ids = list(parent_ids)`
     - `physical_child_chunk_ids = ["UNKNOWN"]`
     - `score_kind = "enr_deterministic_priority"` (скор не является ANN косинусом)
     - `structural_start_verified`, `structural_end_verified`, `continuity_verified`
   - Оценщик `evaluate_normative_evidence()` адаптирован к разделению атрибутов при 100% обратной совместимости.

5. **Тестовые пакеты (84/84 PASS)**:
   - `tests/test_norm_clause_reconstruction_017.py` (C17-01..C17-12): **12/12 PASS** (0.39 с).
   - `tests/test_retrieval_cache_revision_017.py`: **2/2 PASS** (0.13 с).
   - `tests/test_postfix_pilot_real_payload_015_rev1_3.py`: **8/8 PASS** (2.3 с).
   - `tests/test_postfix_pilot_fail_closed_015_rev1_2.py`: **10/10 PASS** (9.9 с).
   - `tests/test_postfix_pilot_fail_closed_015.py`: **10/10 PASS** (6.9 с).
   - `tests/test_retrieval_clause_edition_014.py`: **42/42 PASS** (49.7 с).

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`STATUS`** | **`CODE_GATE: GO_WITH_OFFLINE_SCOPE`** | Кэш изолирован ротацией скоупа v11, атрибуция ENR разделена, матрица C17-01..12 подтверждена. |
| **`CACHE_ROTATION_INTEGRATED`** | **`YES`** | Изменения PR № 1 объединены в `audit/stage4-2-verification` (коммит `2600c04b`). |
| **`ENR_ATTRIBUTION_SEPARATED`** | **`YES`** | Синтетические derived clause_id отделены от физических child IDs, скор маркирован `enr_deterministic_priority`. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу в рамках ТЗ-017 выполнено: строго 0. |
| **`TEST_SUITE_C17_01_12`** | **`12/12 PASS`** | Все 12 сценариев реконструкции норм, атрибуции и изоляции успешно пройдены. |
| **`CACHE_REVISION_SUITE`** | **`2/2 PASS`** | Тесты изоляции устаревшего кэша v10 успешно пройдены. |
| **`TOTAL_TESTS_PASS`** | **`84/84 PASS`** | Полный регрессионный пакет пройден без единого сбоя. |
| **`ISOLATED_COPY_VERIFIED`** | **`YES`** | Изолированная копия проверена через `check_readonly_scope` и `validate_pilot_config`. |
| **`CONSISTENT_SNAPSHOT`** | **`UNVERIFIED`** | Последовательное копирование компонентов в ТЗ-011. |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Совпадение размерности 1024 не доказывает идентичности весов исторического индекса. |
| **`PILOT_NATURE`** | **`DIAGNOSTIC_PILOT_ONLY`** | Сертификация для production заблокирована до подтверждения снимка и модели. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |
| **`NEW_PILOT_AUTHORITY`** | **`REQUIRES_OPERATOR_APPROVAL`** | Для проведения нового пилота с изолированным кэшем требуется отдельная санкция оператора. |

---

## 3. Детальные отчёты этапа

- [POST_PILOT_NORMATIVE_CLAUSE_RECONSTRUCTION_017.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POST_PILOT_NORMATIVE_CLAUSE_RECONSTRUCTION_017.md) — подробный отчёт о реконструкции норм, форензике кэша и матрице тестов.
- [post_pilot_normative_clause_reconstruction_017.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/post_pilot_normative_clause_reconstruction_017.json) — структурированные метаданные этапа.
- [POSTFIX_REAL_DIAGNOSTIC_016.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POSTFIX_REAL_DIAGNOSTIC_016.md) — исторический отчёт ТЗ-016.
