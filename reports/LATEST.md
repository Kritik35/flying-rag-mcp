# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.9 — POST-FIX RETRIEVAL EVIDENCE PILOT (ТЗ `FR-TZ-20261118-015` / Редакция 1.3 от 18.11.2026, SHA-256 `010412b209b22b392473438e8ecf4eeb46e499c85586fe04fb7b415664188583`, 17 458 байт)  
**Статус этапа**: **`WAITING_OPERATOR_SEARCH_APPROVAL` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `HARNESS_REAL_PAYLOAD_CONTRACT: GO` / `HARNESS_FAIL_CLOSED_VERIFIED: YES` / `TEST_SUITE_E15: 8/8 PASS` / `TEST_SUITE_G15_R12: 10/10 PASS` / `TEST_SUITE_P15: 10/10 PASS` / `REGRESSION_014: 42/42 PASS` / `TOTAL_SUITE_PASS: 70/70 PASS` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенное предусловие DEP-014**: **`SATISFIED`** (ТЗ-014 закрыто: коммит кода [`af984382c75a9a9844209dab96350e31d39df804`](https://github.com/Kritik35/flying-rag-mcp/commit/af984382c75a9a9844209dab96350e31d39df804), коммит отчёта [`271ec6183601d045b010f544267198f5af3ed2a1`](https://github.com/Kritik35/flying-rag-mcp/commit/271ec6183601d045b010f544267198f5af3ed2a1), тесты: 42/42 PASS в модуле, 73/73 PASS в регрессии)  
**Коммит кода и тестов ТЗ-015 Rev 1.3 (Phase A)**: [`821cbe05708c8ba627e60a35ec77cd57e8550574`](https://github.com/Kritik35/flying-rag-mcp/commit/821cbe05708c8ba627e60a35ec77cd57e8550574)  
**Родительский коммит отчётов (Phase B Rev 1.2)**: [`3947226e664a7a5b3d990fb72e621e3c75864f35`](https://github.com/Kritik35/flying-rag-mcp/commit/3947226e664a7a5b3d990fb72e621e3c75864f35)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый READ-ONLY)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `11.11.2026 23:36:41` — строго неизменна)  
**Реальные поисковые вызовы к корпусу для текущей задачи**: **СТРОГО 0** (`actual_corpus_search_calls = 0`)  
**Режим**: STRICT OFFLINE / REAL-PAYLOAD CONTRACT VERIFICATION / HARNESS FAIL-CLOSED VERIFICATION / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги реализации и верификации ТЗ-015 Rev 1.3

1. **Устранение замечаний P0-E1 .. P0-E2, P1-E3**:
   - **P0-E1 (Совместимость с реальными полями MCP-выдачи)**: Функция `evaluate_normative_evidence()` адаптирована к нативной схеме `search_documents` (`file_name`, `source_path`, `section`, `derived_label`, `clause_status`, `evidence_status`, `parent_ids`, `chunk_id`). Поддерживается нормализация номеров СП с фиксацией происхождения (`SOURCE_METADATA`, `FILENAME_INFERRED`), строгая проверка года редакции 2020 для Q088, точная изоляция номеров пунктов и строгое разделение физических локаторов от меток.
   - **P0-E2 (Строгая полнота и точность источника)**: `evidence_status == "EVIDENCE_PARTIAL"`, `clause_status == "context_partial"` или наличие маркеров обрезки строго возвращают `FULL_CLAUSE_EVIDENCE = FAIL`. Для Q010 подтверждено обязательное наличие обоих пределов огнестойкости (EI 60 и EI 15). Без независимого сравнения с эталонным текстом источника `SOURCE_FIDELITY` строго равен `UNKNOWN`. `QUALITY_VERIFIED` выставляется в `True` только при условии, что все критерии имеют статус `PASS` (без единого `UNKNOWN` или `FAIL`).
   - **P1-E3 (Телеметрия и строгое разделение пилота)**: Счётчик `actual_corpus_search_calls = 0` остаётся строго на нуле до прямого разрешения оператора. `child_spawned_calls` учитывает только реальные вызовы подпроцесса. Механическая консистентность пары EIG OFF/ON (`MECHANICAL_PAIR_OK = True`) отделена от содержательного качества (`QUALITY_VERIFIED`).

2. **Верификация матриц тестов (70/70 PASS)**:
   - `tests/test_postfix_pilot_real_payload_015_rev1_3.py`: **8/8 PASS** (2.3 с).
   - `tests/test_postfix_pilot_fail_closed_015_rev1_2.py`: **10/10 PASS** (9.9 с).
   - `tests/test_postfix_pilot_fail_closed_015.py`: **10/10 PASS** (6.9 с).
   - `tests/test_retrieval_clause_edition_014.py`: **42/42 PASS** (49.7 с).

3. **Аудиторские статусы неизменности и готовности**:
   - `ISOLATED_COPY_VERIFIED: YES`
   - `CONSISTENT_SNAPSHOT: UNVERIFIED`
   - `MODEL_INDEX_IDENTITY: UNVERIFIED`
   - `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY`
   - `ACTUAL_CORPUS_SEARCH_CALLS: 0`
   - `HARNESS_REAL_PAYLOAD_CONTRACT: GO`
   - `STATUS: WAITING_OPERATOR_SEARCH_APPROVAL`

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`STATUS`** | **`WAITING_OPERATOR_SEARCH_APPROVAL`** | Все требования Rev 1.3 выполнены, матрицы E15 (8/8), G15-R12 (10/10), P15 (10/10) и регрессия 014 (42/42) пройдены, ожидается санкция оператора. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу в рамках подготовки выполнено: строго 0. |
| **`HARNESS_REAL_PAYLOAD_CONTRACT`**| **`GO`** | Оценщик полностью адаптирован к реальным полям MCP-ответа FlyingRAG. |
| **`HARNESS_FAIL_CLOSED_VERIFIED`** | **`YES`** | Утечка в stdout закрыта, строгий rank identity подтверждён, очистка окружения завершена. |
| **`TEST_SUITE_E15_01_08`** | **`8/8 PASS`** | Все 8 сценариев контракта реальных полей и источников успешно пройдены. |
| **`TEST_SUITE_G15_R12`** | **`10/10 PASS`** | Все 10 сценариев безопасности и fail-closed стенда подтверждены. |
| **`TEST_SUITE_P15_01_10`** | **`10/10 PASS`** | Все 10 базовых сценариев ТЗ-015 подтверждены. |
| **`REGRESSION_SUITE_014`** | **`42/42 PASS`** | Полный регрессионный пакет ТЗ-014 пройден без деградации. |
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

- [POSTFIX_PILOT_READINESS_015.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POSTFIX_PILOT_READINESS_015.md) — подробный отчёт о готовности стенда и решении errata Rev 1.3.
- [postfix_pilot_readiness_015.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/postfix_pilot_readiness_015.json) — структурированные метаданные readiness.
