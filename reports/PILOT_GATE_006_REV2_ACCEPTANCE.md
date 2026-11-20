# Stage 4.2.8 — PILOT-GATE-01 Revision 2: Pre-Execution Gate Acceptance Report

**Документ**: Отчёт о приёмке доработок предохранительного гейта PILOT-GATE-01 Revision 2  
**ТЗ**: `FR-TZ-20261116-006` / PILOT-GATE-01 Revision 2 (`17aa5542a802cc84c257fc407dc45d38ab4a062fd1574f088ba33c680bd78096`)  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY / AWAITING_OPERATOR_DECISION**  
**Проверенный коммит кода (tested code anchor)**: [`f009cfe484c09aa2838ff5feb23614c6db0330d3`](https://github.com/Kritik35/flying-rag-mcp/commit/f009cfe484c09aa2838ff5feb23614c6db0330d3)  
**Tree SHA кода**: `8285ddf70565e7e1d6712381a2589be655e30986`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`9d822f7d898ef6a1196366f21d0682c7720eecaf`](https://github.com/Kritik35/flying-rag-mcp/commit/9d822f7d898ef6a1196366f21d0682c7720eecaf) (Tree: `163ab70dc2be38ec6c776266f57ea2d3b42c5eac`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `<PRODUCTION_DB_METADATA>` (размер: 1,485,103,104 байт, WAL: 0 байт, не изменялась)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**  

---

## 1. Резюме закрытия замечаний Revision 2

В рамках ТЗ `FR-TZ-20261116-006` Revision 2 полностью устранены 4 выявленных дефекта предохранительного контура (P0-A, P0-B, P0-C, P0-D) и реализован полный комплект негативных контрактных проверок G2-01..G2-10:

1. **P0-A: Строгая валидация манифеста запросов (`validate_query_manifest`)**:
   - Введено обязательное требование схемы верхнего уровня `flying_rag.pilot_query_manifest.v1`.
   - Введена проверка 64-символьного hex SHA-256 хеша канонической сериализации (`json.dumps(queries, sort_keys=True, ensure_ascii=False)`).
   - Введён строгий whitelist категорий: допускаются исключительно `ACTUAL_NORMATIVE` и `SYNTHETIC_ADVERSARIAL`.
   - Реализована сверка счётчиков заголовка (`total_queries == 105`, `normative_count == 80`, `adversarial_count == 25`).
   - Проверяются поля каждого элемента: непустой строковый `query_id`, 1-based порядковый `position` (1..N без пропусков), непустой `query_text` (строка $\le 10000$ символов; типы `dict`, `int` запрещены).
   - Законный повтор `query_text` с уникальным `query_id` разрешён.
   - Параметр `max_queries <= 0` переведён в fail-closed отказ с 0 вызовов.

2. **P0-B: Проверка процесса на уровне ОС (`verify_process_termination_safety`)**:
   - Реализована OS-level проверка через `psutil`: проверка существования `pid_exists(target_pid)`, считывание и нормализация `proc.exe()`, сопоставление `proc.create_time()`.
   - Реализована корректная трансляция launcher virtualenv на Windows (`pyvenv.cfg` -> базовый интерпретатор Python).
   - Исключена посылка сигналов завершения к чужим или неидентифицированным процессам (0 kill/terminate).
   - Статус жизненного цикла зафиксирован как `PROCESS_LIFECYCLE_PLAN = PLAN_ONLY`.

3. **P0-C: Верификация целостности снимка базы данных (`verify_snapshot_readiness`)**:
   - Чётко разграничены состояния `SNAPSHOT_FILES_PRESENT` и `CONSISTENT_SNAPSHOT_VERIFIED`.
   - Для SQLite проверяется `PRAGMA quick_check == 'ok'` и наличие таблиц в `sqlite_master` с гарантированным освобождением файлового дескриптора в блоке `finally`.
   - Для LanceDB проверяется наличие непустого `index_manifest.json` и физической директории таблицы `documents_1024.lance`.
   - Мусорные байты или пустой манифест `{}` безусловно возвращают `SNAPSHOT_NO_GO`.

4. **P0-D: Предотвращение подмены конфигурации между OFF и ON (`run_real_retrieval_shadow_pilot`)**:
   - Проверка fingerprint и scope выполняется непосредственно перед шагом A (OFF) И непосредственно перед шагом B (ON).
   - В случае мутации YAML во время выполнения OFF шаг B (ON) строго блокируется (0 вызовов ON-worker).
   - Серия немедленно останавливается со статусом `CONFIG_TAMPER_DETECTED` и вердиктом `BLOCKED`.

---

## 2. Матрица негативных тестов G2-01..G2-10

Все 10 обязательных негативных тестов Revision 2 реализованы в `tests/test_real_retrieval_shadow_pilot.py` и успешно пройдены:

| Тест | Проверяемый сценарий | Ожидаемый результат | Фактический результат | Статус |
|:---|:---|:---|:---|:---:|
| **`G2-01`** | Манифест 105 запросов без `schema` или `manifest_sha256` | Отказ `MANIFEST_SCHEMA_INVALID` / `MANIFEST_HASH_MISSING_OR_INVALID`, статус `CONFIG_INVALID`, 0 вызовов | Схемы и хеши проверены, запуск заблокирован с 0 вызовов | **PASS** |
| **`G2-02`** | Произвольная категория (`UNAUTHORIZED_BENCHMARK`), неверные счётчики заголовка, `query_text` с типом dict/int | Отказ `MANIFEST_INVALID_CATEGORY`, `MANIFEST_NORMATIVE_COUNT_MISMATCH`, `MANIFEST_INVALID_QUERY_TEXT` | Все некорректные поля отклонены до запуска | **PASS** |
| **`G2-03`** | Пустой ID, пропуск позиции (1, 2, 4...), неверный хеш; законный повтор `query_text` | Ошибки `MANIFEST_MALICIOUS_OR_EMPTY_ID`, `MANIFEST_POSITION_GAP`; повтор текста разрешён | Ошибочные манифесты отклонены; валидный дубликат текста принят | **PASS** |
| **`G2-04`** | `max_queries = 0` или отрицательное значение | Согласованный отказ `CONFIG_INVALID`, `total_queries_planned = 0`, 0 вызовов | `max_queries=0` и `-10` дают `CONFIG_INVALID` и 0 вызовов | **PASS** |
| **`G2-05`** | Реальный PID с чужим `expected_path` или несовпадающим `start_time` | `safe = False`, отказ `PROCESS_PATH_MISMATCH` или `PROCESS_START_TIME_MISMATCH`, 0 сигналов | Чужие пути и времена отклонены на уровне ОС | **PASS** |
| **`G2-06`** | PID reuse, исчезнувший PID, посторонний слушатель порта 8089 | `PROCESS_NOT_FOUND`, `PORT_8089_IN_USE_BY_FOREIGN_PROCESS`; собственный процесс верифицирован | Чужие PID и порты отвергнуты; собственный процесс подтверждён | **PASS** |
| **`G2-07`** | Мусорные байты в SQLite, пустой `{}` манифест LanceDB, отсутствие таблицы | Отказ `SNAPSHOT_SQLITE_INVALID`, `SNAPSHOT_LANCEDB_EMPTY_MANIFEST`, `SNAPSHOT_LANCEDB_TABLE_NOT_FOUND` | `verify_snapshot_readiness` вернула `False` во всех трёх случаях | **PASS** |
| **`G2-08`** | WAL=0, совпадение хеша сэмпла, но отсутствие доказательства согласованности | `SNAPSHOT_CONSISTENCY_PROOF_REQUIRED`, статус `UNVERIFIED` (не `CONSISTENT_SNAPSHOT_VERIFIED`) | Статус согласованности не присвоен без явного доказательства | **PASS** |
| **`G2-09`** | OFF-поиск меняет YAML на боевые пути: проверка перед ON | Шпион ON-поиска строго 0, серия прервана, `CONFIG_TAMPER_DETECTED`, вердикт `BLOCKED` | Вызовы ON: ровно 0; прерывание зафиксировано; боевые пути защищены | **PASS** |
| **`G2-10`** | Изменение конфигурации/симлинка перед вызовом worker | Остановка с 0 новых worker, статус `CONFIG_INVALID`/`CONFIG_TAMPER_DETECTED`, без ложного GO | Вызовов поиска: 0, статус `CONFIG_INVALID`, вердикт `BLOCKED` | **PASS** |

---

## 3. Сводка выполнения контрактного тестового набора

- **Общее число тестов**: 60
  - Базовые контрактные тесты Stage 4.2.8: 40
  - Негативные контрактные тесты Revision 1 (NG-01..NG-10): 10
  - Негативные контрактные тесты Revision 2 (G2-01..G2-10): 10
- **Пройдено**: **60 / 60 PASS (100%)**
- **Ошибок**: **0**
- **Провалов**: **0**
- **Время выполнения**: 7.749 с
- **Окружение**: `<PRODUCTION_DIR>/python.exe` (Python 3.12, Windows 10 x64, Acer Aspire)

---

## 4. Честная фиксация недоказанных предпосылок

В соответствии с требованиями ТЗ и правилами правдивой метрики, система явно фиксирует следующие ограничения:

1. **`REAL_CORPUS_PILOT: NOT_EXECUTED`**: К боевому корпусу не было сделано ни одного реального поискового запроса (`actual_search_calls = 0`). Все тесты выполнены на изолированных временных фикстурах.
2. **`SNAPSHOT_READY: NO_GO`**: Согласованный изолированный снимок боевой базы ещё не создан и не проверен. Боевая база данных `<PRODUCTION_DB_METADATA>` находится в состоянии READ-ONLY.
3. **`MODEL_INDEX_IDENTITY: UNVERIFIED`**: Сервер эмбеддингов на порту 8089 выключен; соответствие размерности индексов боевой модели не проверялось на реальных весах.
4. **`EMBEDDING_PROFILE: UNVERIFIED`**: Профиль совместимости модели с боевым индексом LanceDB не подтверждён живым прогоном.
5. **`PROCESS_LIFECYCLE_PLAN: PLAN_ONLY`**: Процедура безопасной остановки сервера проверена на контролируемых процессах, но боевой процесс `llama-server.exe` не запускался и не останавливался.
6. **`CROSS_STORE_RECOVERY: BLOCKED`**: Автоматическое сквозное восстановление между LanceDB и SQLite не поддерживается.
7. **`READER_QUARANTINE_ISOLATION: READ_ISOLATION_NOT_PROVEN`**: Режим read-only на уровне подключения SQLite не гарантирует физической изоляции без уровня ОС/контейнеризации.
8. **`PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**: Боевой репозиторий `<PRODUCTION_DIR>/flying-rag-mcp` строго заблокирован на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`.

---

## 5. Форма решения оператора (Operator Decision Form)

Предохранительный гейт полностью подготовлен и аттестован на уровне контракта (`CONTRACT_GATE_READY`). Никаких действий на боевом контуре не производилось.

Оператору предлагается выбрать следующий шаг:

```
[ ] ВАРИАНТ 1: ПОДГОТОВИТЬ БЕЗОПАСНЫЙ СНИМОК ХРАНИЛИЩА (SNAPSHOT PREPARATION)
    - Скопировать metadata.db и lancedb в изолированный каталог <PRODUCTION_DIR>/isolated_pilot_data
    - Выполнить проверку PRAGMA quick_check и верификацию WAL=0 на копии
    - Зафиксировать статус SNAPSHOT_READY: GO

[ ] ВАРИАНТ 2: ПРОВЕРИТЬ СЕРВЕР ЭМБЕДДИНГОВ (EMBEDDING SERVICE VERIFICATION)
    - Проверить наличие бинарного файла llama-server.exe и файла весов модели
    - Сформировать точную команду запуска на изолированном порту 8089
    - Зафиксировать статус MODEL_INDEX_IDENTITY / EMBEDDING_PROFILE

[ ] ВАРИАНТ 3: ОСТАНОВИТЬСЯ НА ТЕКУЩЕМ ЭТАПЕ (GATE VERIFIED)
    - Сохранить текущее состояние CONTRACT_GATE_READY без запуска реального пилота
```
