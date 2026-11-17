# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — AUTO-START-01 PROVENANCE AND PERMISSIONS (ТЗ `FR-TZ-20261117-009` / Редакция 1.0 от 2026-11-17, SHA-256 `5d166b9a747941e22825b0745e72b767bf420a96f99f024871a93af3159a23d3`, 19,999 байт)  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: BLOCKED_SETUP_REQUIRED (GO_PENDING_LIVE_CYCLE) / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED**  
**Принятый код (tested code commit Phase A)**: [`a0dd1bc790df61259885e8c00af895cce3304659`](https://github.com/Kritik35/flying-rag-mcp/commit/a0dd1bc790df61259885e8c00af895cce3304659)  
**Tree SHA кода**: `1ce35b4ac5c93720064b8ff152000358a24091a3`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`704ecf79fcd91d82e763cd68ca21b8158a75a4a2`](https://github.com/Kritik35/flying-rag-mcp/commit/704ecf79fcd91d82e763cd68ca21b8158a75a4a2) (Tree: `f75c4e93abcf2ce11056628f4a8e59aef7a943fc`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`3a63ed72f5bdca2849d28edaa08e0894daa1d1b1`](https://github.com/Kritik35/flying-rag-mcp/commit/3a63ed72f5bdca2849d28edaa08e0894daa1d1b1) (Tree: `a4902418d62ae11b9c81f2b2c00f2c5cbf8652a0`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Текущий операционный статус**: **`CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: BLOCKED_SETUP_REQUIRED / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED / SESSION_RESTART_RECOVERY: CONFIGURED_UNOBSERVED / WINDOWS_POWER_RECOVERY: CONFIGURED_UNOBSERVED / SNAPSHOT_READY: NO_GO / REAL_CORPUS_PILOT: NOT_EXECUTED / PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH  

---

## 1. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`CONTRACT_GATE_READY`** | **`GO`** | 70/70 контрактных тестов пройдены (40 базовых + 10 NG + 10 G2 + 10 G3). Численная конечность, канонический манифест 80/25 и безопасность подтверждены. |
| **`AUTOSTART_CODE_GATE`** | **`GO`** | Устранены замечания ТЗ-009 (P0-S1, P0-S2, P0-O1, P0-O2): статический токен в JSON без внешнего валидатора отклонён fail-closed; двунаправленная проверка запрещает родителя production (`C:\RAG_Acer`), диски (`C:\`), UNC и traversal; артефакты `TEST_ONLY` проверяются на свежесть после dispatch и причинную связь с файл-модифицирующим инструментом; 109/109 тестов пройдены (9 новых S3-01..10 + 12 A4R-01..12 + 18 watcher + 70 shadow pilot). |
| **`AUTOSTART_READY`** | **`BLOCKED_SETUP_REQUIRED`** | Кодовый гейт пройден (`AUTOSTART_CODE_GATE: GO`). На реальном хосте Acer отсутствует настроенная песочница/контейнер для пользователя `almax`; запуск честно заблокирован до настройки оператором. |
| **`AUTOSTART_MODE`** | **`AUTO_EXECUTE_SCOPED`** | Активирован в конфигурации; исполнение заблокировано политикой безопасности и паузой. |
| **`LIVE_GATE`** | **`NOT_EXECUTED`** | На боевом Acer активен операторский стоп-маркер `watcher.pause`. Принудительный обход паузы запрещён регламентом. |
| **`SESSION_RESTART_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Схема v2, durable intent и обработка сбоев настроены в коде; статус зафиксирован контрактными тестами, реальный непредвиденный сбой daemon не симулировался. |
| **`WINDOWS_POWER_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Параметр `StartWhenAvailable = true` включён в планировщике Windows; физический цикл сна/пробуждения оператором непосредственно не наблюдался. |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированная копия боевой базы данных не создавалась. Боевая база данных `C:/RAG_Acer/data_imported/metadata.db` остаётся в режиме READ-ONLY (WAL: 0 байт, не изменялась). |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Сервер эмбеддингов 8089 выключен. Живая проверка соответствия весов модели размерности боевого индекса LanceDB не выполнялась. |
| **`EMBEDDING_PROFILE`** | **`UNVERIFIED`** | Профиль совместимости модели с боевым индексом LanceDB не подтверждён живым прогоном. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | К боевому корпусу выполнено ровно 0 поисковых вызовов (`actual_search_calls = 0`). Все тесты проведены на синтетических фикстурах в temp. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остаётся строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 2. Сводка результатов тестов (109 / 109 PASS)

1. **`tests/test_autostart_provenance_and_permissions.py`**: **9 / 9 PASS** (0.957 с)
   - Целевой пакет проверок S3-01 .. S3-10
2. **`tests/test_autostart_dispatcher.py`**: **12 / 12 PASS** (1.706 с)
   - Регрессионная матрица A4R-01 .. A4R-12 (включая R1–R8 и O-1..O-4)
3. **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS** (1.250 с)
   - Базовые сценарии монитора Google Drive
4. **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS** (13.500 с)
   - Базовые контрактные тесты Stage 4.2.8: 40
   - Негативные контрактные тесты Revision 1 (NG-01..NG-10): 10
   - Негативные контрактные тесты Revision 2 (G2-01..G2-10): 10
   - Негативные контрактные тесты Revision 3 & 3.2 (G3-01..G3-10): 10
5. **Native Module Replay (S3-01 .. S3-08)**: **8 / 8 VERIFIED** (0.245 с)
   - Точные нативные результаты воспроизведения опубликованного модуля:
     - S3-01: `BLOCKED_SETUP_REQUIRED: Runtime isolation cannot be proven from static local configuration`
     - S3-02: `BLOCKED_SETUP_REQUIRED: Runtime isolation attestation rejected: TOKEN_EXPIRED_OR_WORKTREE_MISMATCH`
     - S3-03: `BLOCKED_SETUP_REQUIRED: Prohibited root C:\RAG_Acer\data_imported\metadata.db ancestor C:\RAG_Acer found in allowed_write_roots`
     - S3-04: `Unobserved: (False, BLOCKED), Verified: (True, SECURITY_BOUNDARY_VERIFIED)`
     - S3-05: `TERMINAL_FAILURE: STALE_PREEXISTING_ARTIFACT: Artifact stale_artifact.txt was not modified after task dispatch`
     - S3-06: `TERMINAL_FAILURE: UNVERIFIED_OUTCOME: Required artifact read_only_artifact.txt was not produced by an executed write action in session`
     - S3-07: `UNKNOWN: ORPHANED_TOOL_RESULT: TOOL_RESULT call_id 'call-forged-999' has no matching TOOL_CALL`
     - S3-08: `TERMINAL_SUCCESS: SESSION_TERMINAL_VERIFIED: Correlated terminal outcome, verified causality, and fresh artifacts`

---

## 3. Ссылки на отчётные артефакты

- **Отчёт приёмки ТЗ-009**: [`reports/AUTOSTART_FINAL_GATE_009_ACCEPTANCE.md`](AUTOSTART_FINAL_GATE_009_ACCEPTANCE.md)
- **Машинно-читаемые результаты ТЗ-009 (JSON)**: [`reports/autostart_final_gate_009.json`](autostart_final_gate_009.json)
- **Отчёт приёмки Revision 1.2 (ТЗ-007)**: [`reports/AUTOSTART_FINAL_GATE_007_ACCEPTANCE.md`](AUTOSTART_FINAL_GATE_007_ACCEPTANCE.md)
- **Канонический манифест 105 запросов**: [`tests/pilot_query_manifest_105.json`](../tests/pilot_query_manifest_105.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
