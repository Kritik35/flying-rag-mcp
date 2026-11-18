# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — RETRIEVAL-QUALITY-01 (ТЗ `FR-TZ-20261118-014` / Редакция 1.2 от 18.11.2026, SHA-256 `495d494e8ed2442e77d069aab3aefd255ee989d74852abdcb94df3c8bf0f307f`, 14 080 байт)  
**Статус этапа**: **`RQ14_CODE_GATE: GO` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `OFFLINE_TESTS: 32/32 PASS (63/63 TOTAL)` / `REAL_CORPUS_PILOT_AFTER_FIX: NOT_EXECUTED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенный коммит кода (Phase A code anchor Rev 1.2)**: [`9f3ca6401366386b021e8fc151352b7ede172d96`](https://github.com/Kritik35/flying-rag-mcp/commit/9f3ca6401366386b021e8fc151352b7ede172d96) (Tree: `e258adf90dc6474b1d6920c0b4ee741a59509b99`)  
**Родительский коммит (preceding reports HEAD ТЗ-014 Rev 1.1)**: [`3108aba76df1004df7240ed27b2ce084d35b1e69`](https://github.com/Kritik35/flying-rag-mcp/commit/3108aba76df1004df7240ed27b2ce084d35b1e69)  
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

## 1. Итоги выполнения ТЗ-014 Редакции 1.2 (Errata: Numeric Lists & Decimal Measurements)

В рамках ТЗ-014 Редакции 1.2 устранены замечания независимого аудитора к преждевременному обрезанию нормативных пунктов из-за ложного распознавания элементов нумерованных списков и физических величин в качестве заголовков:

1. **Устранение ложного срабатывания на нумерованные списки (`rag_server/norm_resolver.py`)**:
   - Строки списков вида `1. Клапаны EI 60;` и `2. Воздушные затворы EI 15.` больше не распознаются как разделы верхнего уровня (`cand_sec <= cur_sec` и пунктуация списка `;` / `,`).
   - Исключено ложное обрезание текста пункта как при обработке одиночного чанка, так и при межчанковом сшивании чанков `0021` и `0022`.

2. **Дисквалификация физических десятичных величин**:
   - Строки с десятичными измерениями (`30.5 мм толщина`, `60.0 °C температура`, `1.5 МПа`) больше не распознаются как иерархические пункты благодаря проверке физических единиц и начальных строчных букв.
   - Подпункты `6.10.1`, `6.10.2` надежно сохраняются внутри тела п. `6.10`, а сноски вида `(см. п. 6.11)` не приводят к обрезанию.

3. **Единообразие точек отсечения (Требование 2.4)**:
   - Введена единая вспомогательная функция `_find_next_structural_header_pos()`, вызываемая как при проверке одиночного чанка, так и при межчанковом объединении смежных чанков.
   - Межуровневые переходы (`7. Раздел...`) требуют структурного подтверждения (`Раздел` или заглавный заголовок). При отсутствии достоверного заголовка система возвращает `context_partial` / `EVIDENCE_PARTIAL`.

4. **Офлайн-регрессия N1..N10, F1..F10 и RQ14-01..12**:
   - Реализовано 10 целевых сценариев N1–N10 в `tests/test_retrieval_clause_edition_014.py`.
   - Результат: **32/32 PASS** в модуле ТЗ-014 и **63/63 PASS** во всех регрессионных наборах поиска и норм.

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`RQ14_CODE_GATE`** | **`GO`** | Код точного извлечения пунктов, защиты от ложных заголовков, нумерованных списков и величин доказан 32 тестами. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу в данной задаче выполнено: строго 0. |
| **`OFFLINE_TESTS`** | **`32/32 PASS`** | Все 32 сценария (12 RQ14 + 10 F-сценариев + 10 N-сценариев) успешно пройдены на Phase A SHA `9f3ca640`. |
| **`TOTAL_REGRESSION_TESTS`** | **`63/63 PASS`** | Полный набор тестов качества поиска и норм успешно пройден (время 17.5 с). |
| **`REAL_CORPUS_PILOT_AFTER_FIX`** | **`NOT_EXECUTED`** | Повторный реальный запуск поиска требует отдельного письменного распоряжения оператора. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата таблиц LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остается строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 3. Детальные отчёты этапа

- [RETRIEVAL_CLAUSE_EDITION_014.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/RETRIEVAL_CLAUSE_EDITION_014.md) / [retrieval_clause_edition_014.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/retrieval_clause_edition_014.json) — Отчёт о реализации точного извлечения пунктов норм, защите от нумерованных списков и десятичных величин (Errata Rev 1.2) и машинном различении редакций документов (ТЗ-014 Редакция 1.2).
- [PILOT_EVIDENCE_013.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_EVIDENCE_013.md) / [pilot_evidence_013.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_evidence_013.json) — Проверка достоверности результатов реального пилота, границ чанков и первоисточников норм (ТЗ-013 Редакция 1.0).
- [PILOT_ENTRY_VERIFICATION_012.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_ENTRY_VERIFICATION_012.md) / [pilot_entry_verification_012.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_entry_verification_012.json) — Анализ замечаний аудитора и проверка 12 условий P6-01..P6-12 допуска к пилоту (ТЗ-012 Редакция 1.0).
- [PILOT_SMOKE_011_REV1_1.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_SMOKE_011_REV1_1.md) / [pilot_smoke_011_rev1_1.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_smoke_011_rev1_1.json) — Отчёт о выполнении поискового пилота: создание изолированной копии, проверка модели и 6 реальных поисковых вызовов (ТЗ-011 Редакция 1.1).
