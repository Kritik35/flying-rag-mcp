# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — RETRIEVAL-QUALITY-01 (ТЗ `FR-TZ-20261118-014` / Редакция 1.3 от 18.11.2026, SHA-256 `47397e90974e97ba0725dee46697dcaa0f4c22deaa6061a188fad0877d2a6332`, 15 002 байт)  
**Статус этапа**: **`RQ14_CODE_GATE: GO` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `OFFLINE_TESTS: 42/42 PASS (73/73 TOTAL)` / `REAL_CORPUS_PILOT_AFTER_FIX: NOT_EXECUTED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенный коммит кода (Phase A code anchor Rev 1.3)**: [`af984382c75a9a9844209dab96350e31d39df804`](https://github.com/Kritik35/flying-rag-mcp/commit/af984382c75a9a9844209dab96350e31d39df804) (Tree: `498467c8ae01ab89c5ff2c4fd30eb9919c861a3d`)  
**Родительский коммит (preceding reports HEAD ТЗ-014 Rev 1.2)**: [`66b68c3fd3b06f3fb17a69a9a8b317bf11e5870e`](https://github.com/Kritik35/flying-rag-mcp/commit/66b68c3fd3b06f3fb17a69a9a8b317bf11e5870e)  
**Коммит кода ТЗ-014 Rev 1.2**: [`9f3ca6401366386b021e8fc151352b7ede172d96`](https://github.com/Kritik35/flying-rag-mcp/commit/9f3ca6401366386b021e8fc151352b7ede172d96)  
**Коммит отчёта ТЗ-014 Rev 1.1**: [`3108aba76df1004df7240ed27b2ce084d35b1e69`](https://github.com/Kritik35/flying-rag-mcp/commit/3108aba76df1004df7240ed27b2ce084d35b1e69)  
**Коммит кода ТЗ-014 Rev 1.1**: [`248cd4b5a415d9a52fd65662ac65ed040a8d966f`](https://github.com/Kritik35/flying-rag-mcp/commit/248cd4b5a415d9a52fd65662ac65ed040a8d966f)  
**Коммит отчёта ТЗ-014 Rev 1.0**: [`a67729376bc38c7d2f44e413cdd5aae2149ae6b5`](https://github.com/Kritik35/flying-rag-mcp/commit/a67729376bc38c7d2f44e413cdd5aae2149ae6b5)  
**Коммит кода ТЗ-014 Rev 1.0**: [`1c80ce88c84f88651ea473e2ad17c3e7738d832b`](https://github.com/Kritik35/flying-rag-mcp/commit/1c80ce88c84f88651ea473e2ad17c3e7738d832b)  
**Родительский коммит ТЗ-013**: [`8f543babb6b0cde0a8707d16f16299ba77d903aa`](https://github.com/Kritik35/flying-rag-mcp/commit/8f543babb6b0cde0a8707d16f16299ba77d903aa)  
**Коммит тестовых фикстур ТЗ-013**: [`1c02df66713e9d42885a2c2072c061720f0cab9e`](https://github.com/Kritik35/flying-rag-mcp/commit/1c02df66713e9d42885a2c2072c061720f0cab9e)  
**Коммит отчёта ТЗ-012**: [`e19771bd7d61b6c02f6cc9ee9116842a1bf9fe50`](https://github.com/Kritik35/flying-rag-mcp/commit/e19771bd7d61b6c02f6cc9ee9116842a1bf9fe50)  
**Коммит поискового смоук-теста ТЗ-011 Rev 1.1**: [`8aad12237ca51c510f4ee446f5a4366f118d67af`](https://github.com/Kritik35/flying-rag-mcp/commit/8aad12237ca51c510f4ee446f5a4366f118d67af)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый READ-ONLY)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `1794429401.7884293` — строго неизменна)  
**Реальные поисковые вызовы к корпусу для текущей задачи**: **СТРОГО 0** (`actual_corpus_search_calls = 0`)  
**Режим**: STRICT OFFLINE / SYNTHETIC ISOLATED FIXTURES / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги выполнения ТЗ-014 Редакции 1.3 (Errata: Mixed-case Section Boundary & No Foreign Contamination)

В рамках ТЗ-014 Редакции 1.3 устранены замечания независимого аудитора к сдвигу границы среза при появлении естественных заголовков разделов в смешанном регистре:

1. **Аутентификация заголовков разделов через lookahead (`rag_server/norm_resolver.py`)**:
   - Строки заголовков разделов в смешанном регистре вида `7. Противодымная защита.` (и `7. Противодымная защита` без точки) аутентифицируются по наличию последующих пунктов нового раздела (`7.1`, `7.1.1`).
   - Срез пункта `6.10` завершается строго **до** начала строки `7.`, полностью исключая загрязнение нормативного требования текстом чужого раздела.

2. **Защита элементов перечисления и неоднозначных окончаний**:
   - Числовые элементы перечисления вида `7. Клапаны EI 15.` с преемником `6.11` в тексте надежно распознаются как списки внутри `6.10` и сохраняются в тексте.
   - Неоднозначные строки вида `7. Технические требования.` без подтверждения (`7.1` или `6.11`) отсекаются до строки `7.`, но fail-closed переводятся в статус `context_partial` (`evidence_status: EVIDENCE_PARTIAL`).

3. **Корректный provenance при межчанковом сшивании**:
   - При сшивании, если новый раздел начинается сразу в смежном чанке `0022`, пустой текст не добавляется, а `parent_ids` содержит только реальный чанк `0021` без дублирования.

4. **Офлайн-регрессия H1..H10, N1..N10, F1..F10 и RQ14-01..12**:
   - Реализовано 10 целевых сценариев H1–H10 в `tests/test_retrieval_clause_edition_014.py`.
   - Результат: **42/42 PASS** в модуле ТЗ-014 и **73/73 PASS** во всех регрессионных наборах поиска и норм.

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`RQ14_CODE_GATE`** | **`GO`** | Код точного извлечения пунктов, защиты от ложных заголовков, списков, величин и межуровневых разделов доказан 42 тестами. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу в данной задаче выполнено: строго 0. |
| **`OFFLINE_TESTS`** | **`42/42 PASS`** | Все 42 сценария (12 RQ14 + 10 F-сценариев + 10 N-сценариев + 10 H-сценариев) успешно пройдены на Phase A SHA `af984382`. |
| **`TOTAL_REGRESSION_TESTS`** | **`73/73 PASS`** | Полный набор тестов качества поиска и норм успешно пройден (время 48.4 с). |
| **`REAL_CORPUS_PILOT_AFTER_FIX`** | **`NOT_EXECUTED`** | Повторный реальный запуск поиска требует отдельного письменного распоряжения оператора. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата таблиц LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остается строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 3. Детальные отчёты этапа

- [RETRIEVAL_CLAUSE_EDITION_014.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/RETRIEVAL_CLAUSE_EDITION_014.md) / [retrieval_clause_edition_014.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/retrieval_clause_edition_014.json) — Отчёт о реализации точного извлечения пунктов норм, защите от нумерованных списков, величин, аутентификации межуровневых заголовков (Errata Rev 1.3) и машинном различении редакций документов (ТЗ-014 Редакция 1.3).
- [PILOT_EVIDENCE_013.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_EVIDENCE_013.md) / [pilot_evidence_013.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_evidence_013.json) — Проверка достоверности результатов реального пилота, границ чанков и первоисточников норм (ТЗ-013 Редакция 1.0).
- [PILOT_ENTRY_VERIFICATION_012.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_ENTRY_VERIFICATION_012.md) / [pilot_entry_verification_012.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_entry_verification_012.json) — Анализ замечаний аудитора и проверка 12 условий P6-01..P6-12 допуска к пилоту (ТЗ-012 Редакция 1.0).
- [PILOT_SMOKE_011_REV1_1.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_SMOKE_011_REV1_1.md) / [pilot_smoke_011_rev1_1.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_smoke_011_rev1_1.json) — Отчёт о выполнении поискового пилота: создание изолированной копии, проверка модели и 6 реальных поисковых вызовов (ТЗ-011 Редакция 1.1).
