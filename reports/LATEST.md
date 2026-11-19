# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.10 — POST-FIX REAL RETRIEVAL DIAGNOSTIC / ONE-SHOT PILOT (ТЗ `FR-TZ-20261119-016` от 19.11.2026, SHA-256 `31db6ca8affaacb6dde81fa4770b094bfb3dee3f0fba09ccb0cec605d0627447`, 26 745 байт)  
**Санкция оператора**: `EXPLICIT_GRANTED` (директива от 19.11.2026: не более 6 вызовов: Q004, Q010, Q088-2020, 3 пары EIG OFF/ON, строго на изолированной копии, без изменений production)  
**Статус этапа**: **`COMPLETED_DIAGNOSTIC_PILOT` / `ACTUAL_CORPUS_SEARCH_CALLS: 6` / `MECHANICAL_PILOT_VERDICT: PASS` / `ENGINEERING_EVIDENCE_VERDICT: PARTIAL_RECOVERY` / `FULL_CLAUSE_EVIDENCE: 0/3 PASS` / `SOURCE_FIDELITY: 3/3 UNKNOWN` / `PILOT_QUALITY: UNVERIFIED` / `SHADOW_EIG_VERDICT: PASS` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенное предусловие DEP-015**: **`SATISFIED`** (ТЗ-015 закрыто: коммит кода [`821cbe05708c8ba627e60a35ec77cd57e8550574`](https://github.com/Kritik35/flying-rag-mcp/commit/821cbe05708c8ba627e60a35ec77cd57e8550574), коммит отчёта с errata Rev 1.4 [`f9817ca2c1fc2893ab1992bcc8d54a4013c18585`](https://github.com/Kritik35/flying-rag-mcp/commit/f9817ca2c1fc2893ab1992bcc8d54a4013c18585))  
**Коммит проверенного кода стенда**: [`821cbe05708c8ba627e60a35ec77cd57e8550574`](https://github.com/Kritik35/flying-rag-mcp/commit/821cbe05708c8ba627e60a35ec77cd57e8550574)  
**Родительский коммит отчётов**: [`f9817ca2c1fc2893ab1992bcc8d54a4013c18585`](https://github.com/Kritik35/flying-rag-mcp/commit/f9817ca2c1fc2893ab1992bcc8d54a4013c18585)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый READ-ONLY)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `11.11.2026 23:36:41` — строго неизменна)  
**Реальные поисковые вызовы к корпусу для текущей задачи**: **РОВНО 6** (`actual_corpus_search_calls = 6`, санкционированный лимит соблюдён на 100%)  
**Режим**: STRICT OFFLINE / ISOLATED CORPUS DIAGNOSTIC / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги выполнения диагностического пилота ТЗ-016 (6 вызовов)

1. **Санкция оператора и проведение пилота**:
   - На основании явного разрешения оператора («Разрешаю ТЗ-016 выполнить не более 6 реальных поисковых вызовов Q004, Q010 и Q088-2020 (3 пары EIG OFF/ON)...») после успешного preflight выполнены ровно 6 поисковых вызовов на изолированной копии корпуса `flying_rag_isolated_pilot_corpus_FR011`.
   - Полные сырые текстовые результаты сохранены исключительно в приватном временном файле `postfix_pilot_raw_results_FR-TZ-20261119-016_1795115736_ff95bbe1.json` (SHA-256: `9c0dbeb5bfca30a2e6707affe2d484f26d5c107230e770ef46a6dbc1fcd8fd41`). В публичные отчёты включены только санированные метаданные и сниппеты $\le 200$ символов.

2. **Механическая стабильность и Shadow EIG Observer (`MECHANICAL_PILOT_VERDICT = PASS`)**:
   - Для всех 3 пар запросов ранжирование (топ 1..5) и нормализованная полезная нагрузка при EIG OFF и ON **строго идентичны** (`rank_identical = True`, `normalized_payload_identical = True`).
   - Фоновый наблюдатель Shadow EIG отработал без сбоев (`errors = 0`, `dropped = 0`, `processed = 1` для каждого вызова ON).
   - Влияния наблюдателя на выдачу не зафиксировано. Механический контракт поиска полностью подтверждён.

3. **Предметная инженерная оценка извлечения норм (`PARTIAL_RECOVERY / UNVERIFIED`)**:
   - **Документ и редакция**: Топ-1 документ для всех 3 запросов определён безошибочно (`TARGET_DOC_MATCH = PASS`). Для `Q088-2020` найдена именно редакция 2020 года (`TARGET_EDITION_MATCH = PASS`), что полностью сняло неоднозначность 2012 года из ТЗ-011.
   - **Целевой пункт**: Номера пунктов (6.4, 6.10, 7.1.1) определены безошибочно в Топ-1 (`TARGET_CLAUSE_MATCH = PASS`).
   - **Полнота и границы норм**: **`0/3 PASS`** (все 3 результата получили статус `context_partial`):
     - **Q004 (п. 6.4 СП 7)**: чанк начинается с середины предложения без предшествующего заголовка пункта (обрыв начала).
     - **Q010 (п. 6.10 СП 7)**: вернулся только родительский чанк `973d9901_p_0021` (2 159 симв.). Смежный чанк `973d9901_p_0022` (где содержатся требования к затворам EI 15 / EI 30) **не был сшит** при извлечении из существующей базы. Норма неполная.
     - **Q088-2020 (п. 7.1.1 СП 60.2020)**: чанк захватил хвост предыдущего пункта 6.4.14.
   - **Достоверность источника (`SOURCE_FIDELITY`)**: `UNKNOWN` (независимый внешний эталон текста не привлекался).
   - **Качество пилота (`PILOT_QUALITY`)**: `UNVERIFIED` (`QUALITY_VERIFIED = False` для всех 3 запросов в строгом соответствии с fail-closed контрактом).

4. **Сохранность боевого контура и аудит инвариантов**:
   - Боевая база `metadata.db` (1 485 103 104 байт, WAL = 0 байт, mtime: `11.11.2026 23:36:41`) строго неизменна.
   - Предохранитель `watcher.pause` активен.
   - Боевой репозиторий `flying-rag-mcp` остаётся на коммите `9b498bf5`.
   - Обновление LanceDB отложено (`DEFERRED_NO_CHANGES`).
   - Сертификация для production заблокирована (`BLOCKED_UNVERIFIED_PREREQUISITES`).

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`STATUS`** | **`COMPLETED_DIAGNOSTIC_PILOT`** | Диагностический пилот из 6 санкционированных вызовов завершён, доказательная база собрана. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`6`** | Фактически выполнено ровно 6 реальных поисковых вызовов (лимит соблюдён на 100%). |
| **`MECHANICAL_PILOT_VERDICT`** | **`PASS`** | 3/3 пары EIG OFF/ON выдали 100% идентичные ранги и полезную нагрузку. |
| **`SHADOW_EIG_VERDICT`** | **`PASS`** | Наблюдатель EIG отработал чисто: sub=1, proc=1, err=0, drop=0 на всех 3 вызовах ON. |
| **`DOCUMENT_MATCH_VERDICT`** | **`3/3 PASS`** | СП 7.13130 и СП 60.13330.2020 безошибочно определены в Топ-1. |
| **`EDITION_MATCH_VERDICT`** | **`3/3 PASS`** | Редакция 2020 года для СП 60 определена безошибочно (`FILENAME_INFERRED`). |
| **`CLAUSE_MATCH_VERDICT`** | **`3/3 PASS`** | Пункты 6.4, 6.10, 7.1.1 безошибочно распознаны в Топ-1. |
| **`COMPLETENESS_VERDICT`** | **`0/3 PASS`** | Все 3 нормы имеют статус `context_partial` (дефекты нарезки/сшивки в существующей БД). |
| **`SOURCE_FIDELITY`** | **`3/3 UNKNOWN`** | Отсутствует независимый внешний эталон исходного текста. |
| **`PILOT_QUALITY`** | **`UNVERIFIED`** | Строгий контракт fail-closed: 0/3 норм признаны полным доказательством. |
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

- [POSTFIX_REAL_DIAGNOSTIC_016.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POSTFIX_REAL_DIAGNOSTIC_016.md) — подробный отчёт о 6 реальных поисковых вызовах, анализе границ чанков и доказательной матрице.
- [postfix_real_diagnostic_016.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/postfix_real_diagnostic_016.json) — структурированные метаданные и санированная выдача пилота.
- [POSTFIX_PILOT_READINESS_015.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POSTFIX_PILOT_READINESS_015.md) — отчёт о подготовке стенда и гейтах ТЗ-015 Rev 1.4.
- [postfix_pilot_readiness_015.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/postfix_pilot_readiness_015.json) — структурированные метаданные readiness ТЗ-015.
