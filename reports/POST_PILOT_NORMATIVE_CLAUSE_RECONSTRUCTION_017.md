# Отчёт о реконструкции нормативных пунктов и разделении атрибуции: ТЗ-017 (Stage 4.2.11)

**Документ**: Отчёт о судебно-технической экспертизе причин кэш-риплея ТЗ-016, интеграции ротации ключа кэша (PR № 1), исправлении атрибуции синтетических идентификаторов ENR (C17-09) и валидации матрицы тестов C17-01..C17-12  
**Техническое задание**: [FR-TZ-20261119-017_READONLY_CLAUSE_RECONSTRUCTION_821cbe05_210da126.txt](file:///G:/Мой%20диск/FlyingRAG_TZ_Inbox/FR-TZ-20261119-017_READONLY_CLAUSE_RECONSTRUCTION_821cbe05_210da126.txt)  
**Редакция**: Редакция 1.0 от 19 ноября 2026 года | Размер: 15 883 байта, UTF-8 | SHA-256: `9f4715ff33e53e934bd4f789aa02aa4af8567d43a6c990a573105f480af45ee5`  
**Ветка аудита**: `audit/stage4-2-verification`  
**Базовый коммит отчётов**: [`210da126931da555cb70159391a681b613ba6b7e`](https://github.com/Kritik35/flying-rag-mcp/commit/210da126931da555cb70159391a681b613ba6b7e)  
**Интегрированный коммит PR № 1**: [`2600c04b75c887da4c482f8140d6d87920601f02`](https://github.com/Kritik35/flying-rag-mcp/commit/2600c04b75c887da4c482f8140d6d87920601f02)  
**Коммит проверенного кода (Phase A)**: [`bce9665f80ffaa745cb5ce57fa0d0ff48ff79309`](https://github.com/Kritik35/flying-rag-mcp/commit/bce9665f80ffaa745cb5ce57fa0d0ff48ff79309)  
**Базовый продакшн коммит (Baseline)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, строго READ-ONLY)  
**Реальных вызовов поиска к корпусу**: **СТРОГО 0** (`actual_corpus_search_calls = 0`)  
**Итоговый статус этапа**: **`CODE_GATE: GO_WITH_OFFLINE_SCOPE` / `CACHE_ROTATION_INTEGRATED: YES` / `ENR_ATTRIBUTION_SEPARATED: YES` / `TEST_SUITE_C17: 12/12 PASS` / `CACHE_REVISION_SUITE: 2/2 PASS` / `TOTAL_TESTS_PASS: 84/84 PASS` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**

---

## 1. Судебно-техническая экспертиза: причина дефекта ТЗ-016

В пилоте ТЗ-016 все 6 вызовов (Q004, Q010, Q088-2020) вернули неполные нормы со статусом `context_partial`, при этом первые 200 символов в точности совпали с пилотом ТЗ-011.

### Установленные факты
1. В изолированной базе `metadata.db` в таблице `search_cache` обнаружены строки с ID 976, 977, 978:
   - Созданы: **17.11.2026** в рамках ТЗ-011 с контрактом `retrieval-quality-v10-enr`.
   - Временные метки `last_hit_at`: **19.11.2026 22:14:35, 22:14:56, 22:15:36** (точное время вызовов ТЗ-016).
   - Счётчики `hit_count` инкрементированы до 3.
2. Полезная нагрузка всех 6 вызовов ТЗ-016 побайтово совпала с содержимым этих исторических записей (`FULL PAYLOAD IDENTICAL: True`).
3. **Вывод**: В ходе поиска ТЗ-016 функция `search_documents()` совершила попадание в точный кэш (`SemanticCache.lookup_exact()`) и вернула старый сериализованный JSON. Модули извлечения норм `NormRegistry` и сшивки чанков при выполнении поиска **даже не вызывались**.

---

## 2. Прямая проверка `NormRegistry` на изолированной БД (Read-Only, без поиска)

Прямой вызов `extract_clause_from_doc()` на изолированной базе `flying_rag_isolated_pilot_corpus_FR011\metadata.db` показал, что актуальный код уже корректно восстанавливает целевые нормы:

| Норма | Родительские чанки | Статус контекста | Длина, симв. | Особенности извлечения |
| :--- | :--- | :---: | :---: | :--- |
| **СП 7 п. 6.4** | `973d9901_p_0017` + `973d9901_p_0018` | `context_sufficient` | 1 764 | Заголовок на месте, начало не обрезано, сшивка с 0018 успешна. |
| **СП 7 п. 6.10** | `973d9901_p_0021` + `973d9901_p_0022` | `context_partial` | 3 758 | **Сшивка 0021+0022 выполнена**, требования **EI 30** и **EI 15** присутствуют в тексте! |
| **СП 60 п. 7.1.1** | `3fb687c5_p_0038` | `context_sufficient` | 962 | Начинается строго с пункта 7.1.1, хвост п. 6.4.14 полностью отсечён. |

*Примечание*: Переписывать алгоритм сшивки в `NormRegistry` не требовалось; проблема заключалась исключительно в кэшировании и атрибуции.

---

## 3. Реализованные исправления

### 3.1. Интеграция PR № 1 (Ротация ключа кэша)
- В `rag_server/tools.py` строковый токен скоупа изменён:
  `"retrieval-quality-v10-enr"` $\rightarrow$ `"retrieval-quality-v11-enr-clause-boundary"`.
- Исторические записи в таблице `search_cache` не модифицируются и не удаляются. За счёт смены скоупа старый кэш v10 игнорируется поисковым движком при любых последующих запросах.
- Добавлен модуль `tests/test_retrieval_cache_revision_017.py` (2 теста, PASS), подтверждающий отсутствие воспроизведения устаревших записей.

### 3.2. Разделение атрибуции ENR (Требование C17-09)
Синтетические элементы нормативного извлечения (ENR) больше не выдаются за физические векторные чанки:
1. Добавлены явные атрибутивные поля:
   - `retrieval_origin = "ENR_DERIVED_CLAUSE"`
   - `derived_clause_id = f"clause_{clause_num}"`
   - `physical_parent_ids = list(parent_ids)` (физические идентификаторы из SQLite)
   - `physical_child_chunk_ids = ["UNKNOWN"]` (синтетический пункт не является векторным child-чанком)
   - `score_kind = "enr_deterministic_priority"` (скор является приоритетом нормативного поиска, а не ANN косинусом)
   - `structural_start_verified`, `structural_end_verified`, `continuity_verified`
2. В `tests/postfix_pilot_harness_015.py` оценщик `evaluate_normative_evidence()` дополнен фиксацией новых атрибутов при полном сохранении обратной совместимости API.

---

## 4. Результаты тестовой матрицы C17-01 .. C17-12

| Тест | Приоритет | Назначение | Результат |
| :--- | :---: | :--- | :---: |
| **C17-01** | **P0** | Q010: сшивка 0021+0022 одного документа, наличие EI 60 и EI 15 | **PASS** |
| **C17-02** | **P0** | Q010: при отсутствии 0022 отказ в сшивке, нет выдуманного EI 15 (`context_partial`) | **PASS** |
| **C17-03** | **P0** | Разные `source_path` при одинаковом префиксе останавливают сшивку | **PASS** |
| **C17-04** | **P0** | Q004: отказ в признании неполного начала нормы за `context_sufficient` | **PASS** |
| **C17-05** | **P0** | Q088-2020: отсечение хвоста 6.4.14, сохранение редакции 2020 года | **PASS** |
| **C17-06** | **P0** | Исключение следующего раздела «7. Противодымная защита» из пункта 6.10 | **PASS** |
| **C17-07** | **P0** | Перечисления «1. Клапаны...», «30.5 мм», ссылки на пункты не принимаются за заголовки | **PASS** |
| **C17-08** | **P0** | Ограничение сшивки смежных чанков, предотвращение зацикливания | **PASS** |
| **C17-09** | **P0** | Разделение derived/physical IDs, изоляция скора от ANN | **PASS** |
| **C17-10** | **P1** | `SOURCE_FIDELITY` без внешнего эталона остаётся строго `UNKNOWN` | **PASS** |
| **C17-11** | **P1** | Маркер регрессии: проверка активности всех исторических тестовых пакетов | **PASS** |
| **C17-12** | **P0** | Строго изолированная фикстура: отсутствие обращений к модели, поиску и боевой БД | **PASS** |

### Сводные итоги тестирования (84/84 PASS):
- `tests/test_norm_clause_reconstruction_017.py`: **12/12 PASS** (0.39 с).
- `tests/test_retrieval_cache_revision_017.py`: **2/2 PASS** (0.13 с).
- `tests/test_postfix_pilot_real_payload_015_rev1_3.py`: **8/8 PASS** (2.3 с).
- `tests/test_postfix_pilot_fail_closed_015_rev1_2.py`: **10/10 PASS** (9.9 с).
- `tests/test_postfix_pilot_fail_closed_015.py`: **10/10 PASS** (6.9 с).
- `tests/test_retrieval_clause_edition_014.py`: **42/42 PASS** (49.7 с).

---

## 5. Аудит инвариантов сохранности

```text
================================================================================
ИНВАРИАНТЫ СОХРАННОСТИ ЭТАПА STAGE 4.2.11 (ТЗ-017):
--------------------------------------------------------------------------------
- Боевая база metadata.db: 1 485 103 104 байт, WAL = 0 байт (НЕ МОДИФИЦИРОВАЛАСЬ)
- Предохранитель watcher.pause: АКТИВЕН (на месте)
- Боевой репозиторий flying-rag-mcp: 9b498bf5 (НЕ МОДИФИЦИРОВАЛСЯ)
- Реальных поисковых вызовов в рамках ТЗ-017: СТРОГО 0
- Изолированная копия FR011: верифицирована (read-only доступ к SQLite)
- Допуск к новому пилоту: ТРЕБУЕТ ОТДЕЛЬНОГО РАЗРЕШЕНИЯ ОПЕРАТОРА
================================================================================
```

---

## 6. Детальные отчёты этапа

- [POST_PILOT_NORMATIVE_CLAUSE_RECONSTRUCTION_017.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POST_PILOT_NORMATIVE_CLAUSE_RECONSTRUCTION_017.md) — подробный отчёт о реконструкции норм, форензике кэша и матрице тестов.
- [post_pilot_normative_clause_reconstruction_017.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/post_pilot_normative_clause_reconstruction_017.json) — структурированные метаданные этапа.
- [LATEST.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/LATEST.md) — сводный статус проекта.
