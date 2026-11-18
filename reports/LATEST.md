# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — RETRIEVAL-QUALITY-01 (ТЗ `FR-TZ-20261118-014` / Редакция 1.1 от 18.11.2026, SHA-256 `d22e23be74cecfeb2b27b84cd1bf031ad2a4716f9725249f83ed094734cbd695`, 17 641 байт)  
**Статус этапа**: **`RQ14_CODE_GATE: GO` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `OFFLINE_TESTS: 22/22 PASS (53/53 TOTAL)` / `REAL_CORPUS_PILOT_AFTER_FIX: NOT_EXECUTED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенный коммит кода (Phase A code anchor Rev 1.1)**: [`248cd4b5a415d9a52fd65662ac65ed040a8d966f`](https://github.com/Kritik35/flying-rag-mcp/commit/248cd4b5a415d9a52fd65662ac65ed040a8d966f) (Tree: `0c8335623a0366386abac61d7d15553b1fb7f581`)  
**Родительский коммит (preceding reports HEAD ТЗ-014 Rev 1.0)**: [`a67729376bc38c7d2f44e413cdd5aae2149ae6b5`](https://github.com/Kritik35/flying-rag-mcp/commit/a67729376bc38c7d2f44e413cdd5aae2149ae6b5)  
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

## 1. Итоги выполнения ТЗ-014 Редакции 1.1 (Errata: Heading False-Positive & Displacement Guard)

В рамках ТЗ-014 Редакции 1.1 устранены замечания аудитора к ложному распознаванию заголовков и вытеснению результатов в `quality_pool`:

1. **Устранение ложного срабатывания на заголовки (`rag_server/norm_resolver.py`)**:
   - `NEXT_HEADER_RE` ограничен строгими структурными шаблонами: префиксными нумерованными пунктами/разделами/статьями (`п. 6.11`, `Раздел 7`), именованными таблицами и приложениями (`Таблица 6.1`, `Приложение А`), иерархическими номерами пунктов (`6.11`, `7.1.1`) и номерами разделов с точкой (`7. `).
   - Обычные повествовательные предложения («В помещениях...», «Дополнительно предусматривается...»), маркеры списков (`а)`, `1)`), числовые величины с единицами («30 минут», «60 °C») и строки таблиц больше не принимаются за новые пункты.
   - Подпункты `6.10.1`, `6.10.2` сохраняются внутри п. `6.10`, а сноски вида `(см. п. 6.11)` не вызывают преждевременной остановки.
   - При отсутствии доказанного завершающего заголовка возвращается fail-closed `context_partial`.

2. **Защита от вытеснения полных результатов и маркировка (`rag_server/tools.py`)**:
   - Частичные результаты (`context_status == "context_partial"`, балл 0.85) больше не вставляются безусловно в позицию `0`. Они вставляются по баллу и не вытесняют проверенные полные совпадения (балл >= 0.85) с ранга 1.
   - Добавлено явное поле `evidence_status`: `"USABLE_FOR_ANSWER"` для достаточного контекста и `"EVIDENCE_PARTIAL"` для частичного, транслируемое в результат поиска и трейс.

3. **Офлайн-регрессия F1..F10 и RQ14-01..12**:
   - Добавлено 10 специализированных тестов F1–F10, покрывающих все контрпримеры аудитора.
   - Результат: **22/22 PASS** в `test_retrieval_clause_edition_014` и **53/53 PASS** в общем наборе регрессионных тестов поискового тракта.

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`RQ14_CODE_GATE`** | **`GO`** | Код точного извлечения пунктов, защиты от ложных заголовков и различения редакций доказан 22 тестами. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу в данной задаче выполнено: строго 0. |
| **`OFFLINE_TESTS`** | **`22/22 PASS`** | Все 22 сценария (12 RQ14 + 10 F-сценариев) успешно пройдены на Phase A SHA `248cd4b5`. |
| **`TOTAL_REGRESSION_TESTS`** | **`53/53 PASS`** | Полный набор тестов качества поиска и норм успешно пройден (время 17.2 с). |
| **`REAL_CORPUS_PILOT_AFTER_FIX`** | **`NOT_EXECUTED`** | Повторный реальный запуск поиска требует отдельного письменного распоряжения оператора. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата таблиц LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остается строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 3. Детальные отчёты этапа

- [RETRIEVAL_CLAUSE_EDITION_014.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/RETRIEVAL_CLAUSE_EDITION_014.md) / [retrieval_clause_edition_014.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/retrieval_clause_edition_014.json) — Отчёт о реализации точного извлечения пунктов норм, устранении ложных заголовков (Errata Rev 1.1) и машинном различении редакций (ТЗ-014 Редакция 1.1).
- [PILOT_EVIDENCE_013.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_EVIDENCE_013.md) / [pilot_evidence_013.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_evidence_013.json) — Проверка достоверности результатов реального пилота, границ чанков и первоисточников норм (ТЗ-013 Редакция 1.0).
- [PILOT_ENTRY_VERIFICATION_012.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_ENTRY_VERIFICATION_012.md) / [pilot_entry_verification_012.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_entry_verification_012.json) — Анализ замечаний аудитора и проверка 12 условий P6-01..P6-12 допуска к пилоту (ТЗ-012 Редакция 1.0).
- [PILOT_SMOKE_011_REV1_1.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_SMOKE_011_REV1_1.md) / [pilot_smoke_011_rev1_1.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_smoke_011_rev1_1.json) — Отчёт о выполнении поискового пилота: создание изолированной копии, проверка модели и 6 реальных поисковых вызовов (ТЗ-011 Редакция 1.1).
- [PILOT_EVIDENCE_013.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_EVIDENCE_013.md) / [pilot_evidence_013.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_evidence_013.json) — Проверка достоверности результатов реального пилота, границ чанков и первоисточников норм (ТЗ-013 Редакция 1.0).
- [PILOT_ENTRY_VERIFICATION_012.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_ENTRY_VERIFICATION_012.md) / [pilot_entry_verification_012.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_entry_verification_012.json) — Анализ замечаний аудитора и проверка 12 условий P6-01..P6-12 допуска к пилоту (ТЗ-012 Редакция 1.0).
- [PILOT_SMOKE_011_REV1_1.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_SMOKE_011_REV1_1.md) / [pilot_smoke_011_rev1_1.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_smoke_011_rev1_1.json) — Отчёт о выполнении поискового пилота: создание изолированной копии, проверка модели и 6 реальных поисковых вызовов (ТЗ-011 Редакция 1.1).
