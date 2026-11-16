# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — PILOT-GATE-01 (ТЗ FR-TZ-20261116-006 / Предохранительный гейт, канонический манифест 105 запросов и закрытие путей)  
**Статус документа**: **PREEXECUTION_GATE_COMPLETE / AWAITING_OPERATOR_DECISION**  
**Статус предыдущего отчёта**: Отчёт PILOT-PREP-01 Rev 2 ([`31c24b47`](https://github.com/Kritik35/flying-rag-mcp/commit/31c24b4711d65f3a8efeed84bda4f471fdaf33f2), Tree: `ca2087e3`) проверен рецензентом; выявленные замечания по числу запросов (8 vs 105) и закрытию путей адресованы и закрыты  
**Принятый код (tested code commit)**: [`1ed15103277b4a24f9a06d444efb08bb491e2133`](https://github.com/Kritik35/flying-rag-mcp/commit/1ed15103277b4a24f9a06d444efb08bb491e2133)  
**Tree SHA кода**: `aee8dffa660d1acb251e754ec09549b98eca611c`  
**Отчётный коммит подготовки PILOT-PREP-01 Rev 2**: [`31c24b4711d65f3a8efeed84bda4f471fdaf33f2`](https://github.com/Kritik35/flying-rag-mcp/commit/31c24b4711d65f3a8efeed84bda4f471fdaf33f2)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`  
**Неизменяемый снимок (snapshot anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)  
**Текущий операционный статус**: **`PREEXECUTION_HARNESS_READY: GO / REAL_QUERY_SET: MANIFEST_105_READY / PATH_CLOSURE: VERIFIED / SNAPSHOT_READY: NO_GO / REAL_CORPUS_PILOT: NOT_EXECUTED / PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH  

---

## 1. Официальные вердикты гейта PILOT-GATE-01 (ТЗ FR-TZ-20261116-006)

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`PREEXECUTION_HARNESS_READY`** | **`GO`** | Выполнены все условия Раздела 7 ТЗ 006: канонический 105-позиционный манифест сформирован и проверен; закрыты все 10 runtime-источников путей `_dispatch`; 10/10 обязательных негативных тестов NG-01..10 успешно пройдены; конфигурация изолирована от боевой; смешение S5 с реальными запросами устранено. |
| **`REAL_QUERY_SET`** | **`MANIFEST_105_READY`** | Канонический манифест `tests/pilot_query_manifest_105.json` (SHA-256: `6121e68c5d851eb2fdd36003b9b91cf37ee2bbbec10f50c8db6b309311ba9592`): ровно 105 позиций (80 нормативных `ACTUAL_NORMATIVE` + 25 состязательных `SYNTHETIC_ADVERSARIAL`). Раннер поддерживает настраиваемый манифест с сохранением базового 8-запросного набора по умолчанию. |
| **`PATH_CLOSURE`** | **`VERIFIED`** | Все 10 источников путей классифицированы. Закрыты угрозы: алиас `lancedb.uri` (fail-closed при конфликте), переопределение `FLYING_RAG_METADATA_DB` (очистка в окружении child-процессов + вето в Pre-Execution Guard), символические ссылки/junctions (блокировка), мутация конфига на диске во время серии (детекция дрейфа отпечатка). |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Регламент A—G задокументирован, но физическая копия боевого корпуса 6.68 GB не создавалась, квиесценция на диске не фиксировалась. |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Имена согласованы через нормализатор (`qwen3embedding06b`), но криптографический провенанс связи файла весов GGUF с векторами LanceDB документально не зафиксирован. Требуется начальный smoke-тест (3 пары). |
| **`EMBEDDING_PROFILE`** | **`UNVERIFIED`** | Сервер эмбеддингов выключен (порт 8089 свободен). Стабильность выполнения OpenCL CLBlast на NVIDIA GT 540M остаётся непроверенной. |
| **`CLI_SUPPORT`** | **`PARTIAL`** | Синтаксис флагов проверен по документации `llama-server.exe` build 11057 (флаг `-nkvo` задокументирован). Реальный запуск инференса не производился. |
| **`PROCESS_LIFECYCLE_PLAN`** | **`OWNED_PID_ONLY`** | Утверждён и проверен тестом NG-07: запрещены групповые команды остановки; чужой PID на порту 8089 полностью блокирует остановку и запуск; управление строго по собственному PID. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | Реальный поиск по корпусу не выполнялся; оффлайн-префлайт честно возвращает `BLOCKED_DEPENDENCY` с 0 вызовов поиска. |
| **`CROSS_STORE_RECOVERY`** | **`BLOCKED`** | Распределённая 2PC-транзакция между SQLite и LanceDB отсутствует (архитектурное ограничение). |
| **`READER_QUARANTINE_ISOLATION`** | **`READ_ISOLATION_NOT_PROVEN`** | Прямое чтение LanceDB возвращает чанки изолированных файлов (EIG в режиме shadow не фильтрует выдачу читателю). |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Развёртывание на продакшне строго **ЗАПРЕЩЕНО**. Боевой baseline `9b498bf` остаётся неприкосновенным. |

---

## 2. Сводка результатов тестирования

- **Общий статус контрактного набора**: **PASSED**
- **Контрактных тестов в `tests.test_real_retrieval_shadow_pilot`**: **50**
  - Исходные контрактные тесты (Ревизии 1—4): **40 / 40 PASSED**
  - Обязательные негативные тесты (NG-01..NG-10): **10 / 10 PASSED**
- **Успешно**: **50** (100.0%)
- **Сбоев / Ошибок**: **0**
- **Время выполнения контрактного набора**: **7.234 с**
- **Статус Production Database**: **UNTOUCHED (True)** — размер 1,485,103,104 байт, размер WAL = 0, неизменный sample SHA256 (head_64kb_tail_64kb_sample_plus_size_mtime_journals fingerprint scope; readonly verified).
- **Статус рабочей директории**: **Clean (True)** на момент запуска приёмки.

### Матрица обязательных негативных тестов (Раздел 5 ТЗ 006)
| Тест | Проверяемое требование | Ожидаемый результат | Фактический результат | Статус |
|:---|:---|:---|:---|:---:|
| **`NG-01`** | Подача `max_queries=105` 8-запросному набору | План ровно 8 запросов, без 105 и без `REAL_PILOT_PASS` | `total_queries_planned == 8`, `actual_calls == 0`, `status != REAL_PILOT_PASS` | **PASS** |
| **`NG-02`** | Некорректный/отсутствующий манифест | Отказ до запуска worker (0 calls), `CONFIG_INVALID`, `BLOCKED` | `CONFIG_INVALID`, 0 вызовов поиска, `spy.call_count == 0` | **PASS** |
| **`NG-03`** | 105-позиционный канонический манифест | 105 позиций, 210 плановых вызовов OFF/ON в счётчиках, 0 реальных вызовов | `planned == 105`, `norm == 80`, `adv == 25`, `actual == 0`, `verdict == BLOCKED` | **PASS** |
| **`NG-04`** | Конфликтующий алиас или `FLYING_RAG_METADATA_DB` в прод | Вето до старта: `NO_GO` и 0 worker; запрет записи в боевую базу | Алиас отклонён, `scope=BLOCKED_READONLY_NOT_PROVEN`, 0 вызовов | **PASS** |
| **`NG-05`** | Символическая ссылка или подмена конфига на диске | Немедленный разрыв цикла, `CONFIG_TAMPER_DETECTED`, вердикт `BLOCKED` | Детекция дрейфа fingerprint на диске, аварийный выход, 0 записей в прод | **PASS** |
| **`NG-06`** | Неподтверждённый snapshot, грязный WAL, дрейф хеша | Отказ копирования/поиска, `SNAPSHOT_UNCONFIRMED_DIRTY_WAL` | WAL > 0, неверный хеш, нет манифеста — все сценарии дают `SNAPSHOT_NO_GO` | **PASS** |
| **`NG-07`** | Чужой PID на порту 8089 / несовпадение имени | Запрет отправки сигнала завершения (`NO kill`), сохранение чужого процесса | `PORT_8089_IN_USE_BY_FOREIGN_PROCESS`, чужой PID не завершается | **PASS** |
| **`NG-08`** | Недоступный backend, модель, нет телеметрии, пустой ответ | `NO_GO` с честной раздельной классификацией причин | Оффлайн -> `BLOCKED_DEPENDENCY`; нет телеметрии -> `FAILED`; пустой ответ -> `search_errors` | **PASS** |
| **`NG-09`** | Исчерпание общего дедлайна серии | Корректное завершение child-процессов, без ложного GO и усечения $N$ | `planned == 10` сохранено, `completed < 10`, `DEADLINE_EXCEEDED`, `BLOCKED` | **PASS** |
| **`NG-10`** | Идемпотентность повторного запуска | Полное совпадение контрольных сумм и статусов, отсутствие дрейфа | Все поля `verdict`, `status`, `config_fingerprint`, `manifest_sha256` идентичны | **PASS** |

---

## 3. Ссылки на подробные технические артефакты
- **Полный отчёт гейта PILOT-GATE-01 (ТЗ 006)**: [`reports/PILOT_GATE_006.md`](PILOT_GATE_006.md)
- **Машинно-читаемые результаты гейта (JSON)**: [`reports/pilot_gate_006.json`](pilot_gate_006.json)
- **Канонический манифест 105 запросов**: [`tests/pilot_query_manifest_105.json`](../tests/pilot_query_manifest_105.json)
- **Отчёт подготовки пилота PILOT-PREP-01 Rev 2 (ТЗ 005)**: [`reports/PILOT_PREPARATION_005.md`](PILOT_PREPARATION_005.md)
- **Машинно-читаемый план подготовки пилота (JSON)**: [`reports/pilot_preparation_005.json`](pilot_preparation_005.json)
- **Специальный отчёт Revision 4 (Pre-Execution Readonly Gate)**: [`reports/stage4_2_8_rev4_readonly_gate.json`](stage4_2_8_rev4_readonly_gate.json)
- **Полный отчёт приёмки Stage 4.2.8 Rev 4**: [`reports/STAGE4_2_8_REV4_ACCEPTANCE.md`](STAGE4_2_8_REV4_ACCEPTANCE.md)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
