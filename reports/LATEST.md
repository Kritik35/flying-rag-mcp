# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — RETRIEVAL-QUALITY-01 (ТЗ `FR-TZ-20261118-014` / Редакция 1.0 от 18.11.2026, SHA-256 `aa2bdd63f0f953719c0d9088e84f49b40147b8f18f5627f4cd93ecdd5e9a99e9`, 25 687 байт)  
**Статус этапа**: **`RQ14_CODE_GATE: GO` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `OFFLINE_TESTS: 12/12 PASS (43/43 TOTAL)` / `REAL_CORPUS_PILOT_AFTER_FIX: NOT_EXECUTED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенный коммит кода (Phase A code anchor)**: [`1c80ce88c84f88651ea473e2ad17c3e7738d832b`](https://github.com/Kritik35/flying-rag-mcp/commit/1c80ce88c84f88651ea473e2ad17c3e7738d832b) (Tree: `93287fef88be537f211159a720ced7a8a60aa394`)  
**Родительский коммит (preceding reports HEAD ТЗ-013)**: [`8f543babb6b0cde0a8707d16f16299ba77d903aa`](https://github.com/Kritik35/flying-rag-mcp/commit/8f543babb6b0cde0a8707d16f16299ba77d903aa)  
**Коммит тестовых фикстур ТЗ-013**: [`1c02df66713e9d42885a2c2072c061720f0cab9e`](https://github.com/Kritik35/flying-rag-mcp/commit/1c02df66713e9d42885a2c2072c061720f0cab9e)  
**Коммит отчёта ТЗ-012**: [`e19771bd7d61b6c02f6cc9ee9116842a1bf9fe50`](https://github.com/Kritik35/flying-rag-mcp/commit/e19771bd7d61b6c02f6cc9ee9116842a1bf9fe50)  
**Коммит поискового смоук-теста ТЗ-011 Rev 1.1**: [`8aad12237ca51c510f4ee446f5a4366f118d67af`](https://github.com/Kritik35/flying-rag-mcp/commit/8aad12237ca51c510f4ee446f5a4366f118d67af)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый READ-ONLY)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `1794429401.7884293` — строго неизменна)  
**Реальные поисковые вызовы к корпусу для текущей задачи**: **СТРОГО 0** (`actual_corpus_search_calls = 0`)  
**Режим**: STRICT OFFLINE / SYNTHETIC ISOLATED FIXTURES / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги выполнения ТЗ-014 (RETRIEVAL-QUALITY-01)

В рамках ТЗ-014 устранены замечания аудитора к качеству извлечения норм и оформлению отчётности:

1. **Исправление опечаток в Git SHA**:
   - В отчётах ТЗ-013 были ошибочно указаны несуществующие полные хеши с опечатками в хвостах.
   - Вся цепочка сверена непосредственно с объектами Git: проверенный Phase A коммит `1c80ce88c84f88651ea473e2ad17c3e7738d832b` опирается на реальный reports HEAD ТЗ-013 `8f543babb6b0cde0a8707d16f16299ba77d903aa`, его родитель `1c02df66713e9d42885a2c2072c061720f0cab9e` и reports HEAD ТЗ-012 `e19771bd7d61b6c02f6cc9ee9116842a1bf9fe50`.

2. **Модернизация рабочего кода поиска (`rag_server`)**:
   - `rag_server/norm_resolver.py`:
     - `extract_clause_from_doc`: структурная нарезка от заголовка до следующего заголовка (`NEXT_HEADER_RE`), предотвращающая захват посторонних пунктов.
     - Ограниченное сшивание соседних родительских чанков (`0021` + `0022`) с доказанным порядком следования и формированием полей провененса `parent_ids` и `is_stitched`.
     - Корректная оценка баланса скобок с очисткой русских маркеров списков (`а)`, `б)`).
     - `resolve_all`: блокировка многоредакционных запросов без года (`ambiguous_editions` / `EDITION_REQUIRED`) и исправление ошибки `sort_key` при отсутствии года у кандидата.
   - `rag_server/tools.py`:
     - Pre-cache edition guard: блокировка неоднозначных запросов до обращения к дисковому кэшу с возвратом структурированных конвертов ошибки, валидируемых `is_error_payload`.
     - Разделение совместимого `derived_label` от физических `parent_ids`.
     - Ограничение балла неполных чанков (0.85 вместо принудительного 1.0).

3. **Офлайн-регрессия RQ14-01..12**:
   - Все 12 тестов используют импорт исправленных модулей и выполняются на изолированных временных базах.
   - Результат: **12/12 PASS** (суммарно 43/43 PASS со смежными тестами качества).

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`RQ14_CODE_GATE`** | **`GO`** | Код точного извлечения пунктов норм и различения редакций реализован и доказан 12 тестами. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу в данной задаче выполнено: строго 0. |
| **`OFFLINE_TESTS`** | **`12/12 PASS`** | Все 12 сценариев RQ14-01..12 успешно пройдены на Phase A SHA `1c80ce88`. |
| **`REAL_CORPUS_PILOT_AFTER_FIX`** | **`NOT_EXECUTED`** | Повторный реальный запуск поиска требует отдельного письменного распоряжения оператора. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата таблиц LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остается строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 3. Детальные отчёты этапа

- [RETRIEVAL_CLAUSE_EDITION_014.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/RETRIEVAL_CLAUSE_EDITION_014.md) / [retrieval_clause_edition_014.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/retrieval_clause_edition_014.json) — Отчёт о реализации точного извлечения пунктов норм, сшивания чанков и машинном различении редакций (ТЗ-014 Редакция 1.0).
- [PILOT_EVIDENCE_013.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_EVIDENCE_013.md) / [pilot_evidence_013.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_evidence_013.json) — Проверка достоверности результатов реального пилота, границ чанков и первоисточников норм (ТЗ-013 Редакция 1.0).
- [PILOT_ENTRY_VERIFICATION_012.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_ENTRY_VERIFICATION_012.md) / [pilot_entry_verification_012.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_entry_verification_012.json) — Анализ замечаний аудитора и проверка 12 условий P6-01..P6-12 допуска к пилоту (ТЗ-012 Редакция 1.0).
- [PILOT_SMOKE_011_REV1_1.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_SMOKE_011_REV1_1.md) / [pilot_smoke_011_rev1_1.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_smoke_011_rev1_1.json) — Отчёт о выполнении поискового пилота: создание изолированной копии, проверка модели и 6 реальных поисковых вызовов (ТЗ-011 Редакция 1.1).
