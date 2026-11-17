# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — PILOT-GATE-01 Revision 2 (ТЗ `FR-TZ-20261116-006` / Строгая валидация манифеста 105, OS-level проверка процессов, целостность снимка и перехват мутации конфига)  
**Статус документа**: **CONTRACT_GATE_READY / AWAITING_OPERATOR_DECISION**  
**Статус предыдущего отчёта**: Отчёт PILOT-GATE-01 Rev 1 ([`9d822f7d`](https://github.com/Kritik35/flying-rag-mcp/commit/9d822f7d898ef6a1196366f21d0682c7720eecaf), Tree: `163ab70d`) проверен рецензентом; замечания по манифесту (P0-A), проверке PID (P0-B), снимку (P0-C), мутации конфигурации (P0-D) полностью устранены  
**Принятый код (tested code commit)**: [`f009cfe484c09aa2838ff5feb23614c6db0330d3`](https://github.com/Kritik35/flying-rag-mcp/commit/f009cfe484c09aa2838ff5feb23614c6db0330d3)  
**Tree SHA кода**: `8285ddf70565e7e1d6712381a2589be655e30986`  
**Предыдущий отчётный коммит**: [`9d822f7d898ef6a1196366f21d0682c7720eecaf`](https://github.com/Kritik35/flying-rag-mcp/commit/9d822f7d898ef6a1196366f21d0682c7720eecaf)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`  
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)  
**Текущий операционный статус**: **`PREEXECUTION_HARNESS_READY: CONTRACT_GATE_READY / REAL_QUERY_SET: MANIFEST_105_READY / PATH_CLOSURE: VERIFIED / SNAPSHOT_READY: NO_GO / REAL_CORPUS_PILOT: NOT_EXECUTED / PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH  

---

## 1. Официальные вердикты гейта PILOT-GATE-01 Revision 2 (ТЗ FR-TZ-20261116-006 Rev 2)

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`PREEXECUTION_HARNESS_READY`** | **`CONTRACT_GATE_READY`** | Выполнены все условия ТЗ 006 Rev 2: строгая валидация манифеста 105 запросов (`flying_rag.pilot_query_manifest.v1`, канонический SHA-256 хеш, whitelist категорий, проверка типов); OS-level верификация владения PID через `psutil`; проверка согласованности SQLite (`PRAGMA quick_check`) и LanceDB (`index_manifest.json`); перехват мутации конфига между OFF и ON (ON строго 0 при подмене); 10/10 тестов G2-01..10 и 10/10 NG-01..10 пройдены (60/60 в сумме). |
| **`REAL_QUERY_SET`** | **`MANIFEST_105_READY`** | Канонический манифест `tests/pilot_query_manifest_105.json` (SHA-256: `6121e68c5d851eb2fdd36003b9b91cf37ee2bbbec10f50c8db6b309311ba9592`): ровно 105 позиций (80 нормативных `ACTUAL_NORMATIVE` + 25 состязательных `SYNTHETIC_ADVERSARIAL`). |
| **`PATH_CLOSURE`** | **`VERIFIED`** | Все 10 runtime-источников путей проверены. `lancedb.uri` блокируется при конфликте; `FLYING_RAG_METADATA_DB` очищается и валидируется; боевые пути защищены. |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированная копия боевой базы данных не создавалась и не проверялась. Боевая база данных `C:/RAG_Acer/data_imported/metadata.db` остаётся в режиме READ-ONLY (WAL: 0 байт, размер: 1,485,103,104 байт, не изменялась). |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Сервер эмбеддингов 8089 выключен. Живая проверка соответствия весов модели размерности боевого индекса LanceDB не выполнялась. |
| **`EMBEDDING_PROFILE`** | **`UNVERIFIED`** | Профиль совместимости модели с боевым индексом LanceDB не подтверждён живым прогоном. |
| **`CLI_SUPPORT`** | **`PARTIAL`** | CLI-инструменты валидированы на уровне кода/скриптов, но автономное развёртывание требует согласованной сборки окружения. |
| **`PROCESS_LIFECYCLE_PLAN`** | **`PLAN_ONLY`** | Безопасная процедура остановки верифицирована на уровне ОС через `psutil` на контролируемых процессах, но боевой процесс `llama-server.exe` не запускался. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | К боевому корпусу выполнено ровно 0 поисковых вызовов (`actual_search_calls = 0`). Все тесты проведены на синтетических фикстурах в temp. |
| **`CROSS_STORE_RECOVERY`** | **`BLOCKED`** | Автоматическое кросс-хранилищное восстановление между LanceDB и SQLite заблокировано. |
| **`READER_QUARANTINE_ISOLATION`** | **`READ_ISOLATION_NOT_PROVEN`** | Режим read-only SQLite не гарантирует физическую изоляцию без ОС-контейнеризации. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остаётся строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 2. Результаты тестов Revision 2 (G2-01..G2-10)

| Тест | Проверяемый сценарий | Ожидаемый результат | Фактический результат | Статус |
|:---|:---|:---|:---|:---:|
| **`G2-01`** | Манифест 105 без `schema` или `manifest_sha256` | Отказ схемы/хеша, `CONFIG_INVALID`, 0 вызовов | Отказ зафиксирован, 0 вызовов | **PASS** |
| **`G2-02`** | Произвольная категория, неверные счётчики, `query_text` dict/int | Отказ `MANIFEST_INVALID_CATEGORY`, неверный заголовок, тип текста | Все некорректные поля отклонены | **PASS** |
| **`G2-03`** | Пустой ID, пропуск позиции (1, 2, 4...), неверный хеш; законный повтор текста | Ошибки ID и позиции; законный повтор текста разрешён | Дефекты отклонены, повтор принят | **PASS** |
| **`G2-04`** | `max_queries = 0` или отрицательный | `CONFIG_INVALID`, `total_queries_planned = 0`, 0 вызовов | `max_queries=0` и `-10` дают 0 вызовов | **PASS** |
| **`G2-05`** | Реальный PID с чужим `expected_path` или `start_time` | Отказ `PROCESS_PATH_MISMATCH` / `PROCESS_START_TIME_MISMATCH`, 0 сигналов | Чужие процессы и времена отвергнуты | **PASS** |
| **`G2-06`** | PID reuse, исчезнувший PID, чужой порт 8089 | `PROCESS_NOT_FOUND`, `PORT_8089_IN_USE_BY_FOREIGN_PROCESS`; собственный процесс проверен | Чужие процессы отклонены, свой подтверждён | **PASS** |
| **`G2-07`** | Мусор в SQLite, пустой `{}` манифест LanceDB, нет таблицы | Отказ `SNAPSHOT_SQLITE_INVALID`, пустой манифест, нет таблицы | Все дефекты снимка отвергнуты | **PASS** |
| **`G2-08`** | WAL=0, совпадение хеша сэмпла, нет доказательства согласованности | `SNAPSHOT_CONSISTENCY_PROOF_REQUIRED`, статус `UNVERIFIED` | Статус согласованности не присвоен без доказательств | **PASS** |
| **`G2-09`** | OFF-поиск меняет YAML на боевые пути: проверка перед ON | Шпион ON-поиска строго 0, серия прервана, `CONFIG_TAMPER_DETECTED`, `BLOCKED` | Вызовов ON: строго 0; серия остановлена | **PASS** |
| **`G2-10`** | Изменение конфигурации/симлинка перед вызовом worker | Остановка с 0 новых worker, статус `CONFIG_INVALID`, без ложного GO | Вызовов поиска: 0, вердикт `BLOCKED` | **PASS** |

---

## 3. Ссылки на отчётные артефакты
- **Полный отчёт приёмки Revision 2**: [`reports/PILOT_GATE_006_REV2_ACCEPTANCE.md`](PILOT_GATE_006_REV2_ACCEPTANCE.md)
- **Машинно-читаемые результаты Revision 2 (JSON)**: [`reports/pilot_gate_006_rev2.json`](pilot_gate_006_rev2.json)
- **Канонический манифест 105 запросов**: [`tests/pilot_query_manifest_105.json`](../tests/pilot_query_manifest_105.json)
- **Предыдущий отчёт Revision 1**: [`reports/PILOT_GATE_006.md`](PILOT_GATE_006.md)
- **Машинно-читаемые результаты Revision 1 (JSON)**: [`reports/pilot_gate_006.json`](pilot_gate_006.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
