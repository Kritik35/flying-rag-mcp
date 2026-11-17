# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — PILOT-GATE-01 Revision 3.2 + AUTO-START-01 Revision 2 (ТЗ `FR-TZ-20261117-006` / Редакция 3.2 от 2026-11-17, SHA-256 `eff089f246df4b191fb1334f5999162f33f05127117ce7287ce617a0613be16d`)  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_READY: GO_PENDING_LIVE_CYCLE / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED**  
**Принятый код (tested code commit)**: [`9530a5962b660031283864a83b9a5a6256002f09`](https://github.com/Kritik35/flying-rag-mcp/commit/9530a5962b660031283864a83b9a5a6256002f09)  
**Tree SHA кода**: `27f77700c2a13e3eae649ba594f283ac1a86902a`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`ecd91f04a4743b1a6bde14d932326d67db7c485b`](https://github.com/Kritik35/flying-rag-mcp/commit/ecd91f04a4743b1a6bde14d932326d67db7c485b) (Tree: `b0abd268a945fd36886770f8aa84a5af5f45611e`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`238ae2668aa1985996c439d4bffc428572a18a44`](https://github.com/Kritik35/flying-rag-mcp/commit/238ae2668aa1985996c439d4bffc428572a18a44) (Tree: `6f78e3da04700a02c9f993d8a8c9363f8fb42b51`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, не изменялась)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Текущий операционный статус**: **`CONTRACT_GATE_READY: GO / AUTOSTART_READY: GO_PENDING_LIVE_CYCLE / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / REAL_AGENT_DISPATCH: VERIFIED / REAL_DRIVE_DELIVERY: VERIFIED / SESSION_RESTART_RECOVERY: CONFIGURED_UNOBSERVED / WINDOWS_POWER_RECOVERY: CONFIGURED_UNOBSERVED / SNAPSHOT_READY: NO_GO / REAL_CORPUS_PILOT: NOT_EXECUTED / PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH  

---

## 1. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`CONTRACT_GATE_READY`** | **`GO`** | Выполнены все условия ТЗ 006 Редакции 3.2: числовая конечность `math.isfinite()` в P0-B (NaN/Inf/bool/0.0 вызывают отказ `OWNED_RECORD_START_TIME_INVALID`); канонический гейт 80/25 в P0-D (custom манифесты получают `MANIFEST_CUSTOM_105` и `full_105_go_eligible = False`); 70/70 контрактных тестов пройдены (40 базовых + 10 NG + 10 G2 + 10 G3). |
| **`AUTOSTART_READY`** | **`GO_PENDING_LIVE_CYCLE`** | Механизм автозапуска полностью исправлен по замечаниям Редакции 3.2: Exit=0 даёт `DISPATCH_CONFIRMED`; блокировка охватывает жизненный цикл сессии агента (`ACTIVE_WORKER_BUSY`); при конфликте редакций выставляется `REVISION_CONFLICT` в карантине; вето клауз-ориентировано; 12/12 сценариев AS-01..AS-12 пройдены (CONTRACT_ONLY). Финальный статус GO ожидает завершения первой сквозной сессии без дублей. |
| **`AUTOSTART_MODE`** | **`AUTO_EXECUTE_SCOPED`** | Активирован в `state.json` и проверен через CLI `--enable-autostart` и `--status`. |
| **`REAL_AGENT_DISPATCH`** | **`VERIFIED`** | Подключён нативный интерфейс Antigravity CLI/RPC `C:\Users\almax\.gemini\antigravity\bin\agentapi.bat` (`language_server.exe agentapi`). Команды `new-conversation`, `get-conversation-metadata`, `send-message` проверены. |
| **`REAL_DRIVE_DELIVERY`** | **`VERIFIED`** | Служба Task Scheduler `FlyingRAG_Drive_Inbox_Watcher` каждые 5 минут (`PT5M`) опрашивает `G:\Мой диск\FlyingRAG_TZ_Inbox` под интерактивным токеном `almax`. Доставка ТЗ проверена. |
| **`SESSION_RESTART_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Схема v2 и обработка сбоев настроены в коде; живой рестарт сессии зафиксирован контрактным тестом AS-06, но не в реальном сбое боевого цикла. |
| **`WINDOWS_POWER_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Параметр `StartWhenAvailable = true` включён в планировщике Windows; физический цикл сна/пробуждения оператором непосредственно не наблюдался. |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированная копия боевой базы данных не создавалась и не проверялась. Боевая база данных `C:/RAG_Acer/data_imported/metadata.db` остаётся в режиме READ-ONLY (WAL: 0 байт, не изменялась). |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Сервер эмбеддингов 8089 выключен. Живая проверка соответствия весов модели размерности боевого индекса LanceDB не выполнялась. |
| **`EMBEDDING_PROFILE`** | **`UNVERIFIED`** | Профиль совместимости модели с боевым индексом LanceDB не подтверждён живым прогоном. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | К боевому корпусу выполнено ровно 0 поисковых вызовов (`actual_search_calls = 0`). Все тесты проведены на синтетических фикстурах в temp. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остаётся строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 2. Сводка результатов тестов (100 / 100 PASS)

1. **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS** (11.373 с)
   - Базовые контрактные тесты Stage 4.2.8: 40
   - Негативные контрактные тесты Revision 1 (NG-01..NG-10): 10
   - Негативные контрактные тесты Revision 2 (G2-01..G2-10): 10
   - Негативные контрактные тесты Revision 3 & 3.2 (G3-01..G3-10): 10
2. **`tests/test_autostart_dispatcher.py`**: **12 / 12 PASS** (1.915 с)
   - Сценарии AS-01..AS-12 (жизненный цикл, очередь, мьютекс сессии, crash recovery, санитаризация, клауз-вето, pause, evidence map)
3. **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS** (0.889 с)
   - Базовые сценарии монитора Google Drive

---

## 3. Ссылки на отчётные артефакты

- **Отчёт приёмки Revision 3.2 гейта**: [`reports/PILOT_GATE_006_REV3_2_ACCEPTANCE.md`](PILOT_GATE_006_REV3_2_ACCEPTANCE.md)
- **Машинно-читаемые результаты Revision 3.2 (JSON)**: [`reports/pilot_gate_006_rev3_2.json`](pilot_gate_006_rev3_2.json)
- **Отчёт приёмки AUTO-START-01 Revision 2**: [`reports/AUTO_START_001_REV2_ACCEPTANCE.md`](AUTO_START_001_REV2_ACCEPTANCE.md)
- **Машинно-читаемые результаты AUTO-START-01 Revision 2 (JSON)**: [`reports/auto_start_001_rev2.json`](auto_start_001_rev2.json)
- **Отчёт приёмки Revision 3 гейта**: [`reports/PILOT_GATE_006_REV3_ACCEPTANCE.md`](PILOT_GATE_006_REV3_ACCEPTANCE.md)
- **Канонический манифест 105 запросов**: [`tests/pilot_query_manifest_105.json`](../tests/pilot_query_manifest_105.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
