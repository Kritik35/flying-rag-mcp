# Stage 4.2.8 — AUTO-START-01 Final Acceptance Report (TZ-010 Rev 1.1)

**Документ**: Отчёт об адресном устранении дефектов сопоставления вызовов и изоляции каталогов артефактов (ТЗ `FR-TZ-20261117-010` / Редакция 1.1 от 2026-11-17)  
**ТЗ**: `FR-TZ-20261117-010` / Stage 4.2.8 / AUTO-START-01 / Адресное устранение дефектов сопоставления вызовов и изоляции каталогов (LIMITED CODE CLOSURE)  
**SHA-256 ТЗ**: `b8aad4dbed91627abb5cdff239f1b1067e440b31eeae2df3f0590c44ceb1f664` (15,079 байт)  
**Локальный путь ТЗ**: [FR-TZ-20261117-010_REV1_1_PAIR_AND_JOB_ROOT_dcf98d50_2bc75d4a.txt](<FILE_URI_REDACTED>)  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: BLOCKED_SETUP_REQUIRED (GO_PENDING_LIVE_CYCLE) / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED**  

---

## 1. Проверенная цепочка коммитов (Git Provenance)

- **Репозиторий**: `https://github.com/Kritik35/flying-rag-mcp`
- **Целевая ветка**: `audit/stage4-2-verification`
- **Проверенный коммит кода (Phase A tested code anchor)**: [`9b95161eaf8bfe7b512babc9dacc8d3c19cbc5d4`](https://github.com/Kritik35/flying-rag-mcp/commit/9b95161eaf8bfe7b512babc9dacc8d3c19cbc5d4)
  - **Tree SHA кода**: `dce08a118d1ca1dac28c1082b3de9531bc5b2f20`
  - **Parent SHA**: `2bc75d4ac1e81fd2b13916116818c7ee85c09695`
- **Предыдущий отчётный коммит (preceding reports HEAD)**: [`2bc75d4ac1e81fd2b13916116818c7ee85c09695`](https://github.com/Kritik35/flying-rag-mcp/commit/2bc75d4ac1e81fd2b13916116818c7ee85c09695) (Tree: `325fe51dd8c532f305c7cf64b04d0fe2d0bdc417`)
- **Предыдущий коммит кода (prior tested code anchor)**: [`dcf98d5039808b01462b420993feba48ac600cfe`](https://github.com/Kritik35/flying-rag-mcp/commit/dcf98d5039808b01462b420993feba48ac600cfe) (Tree: `dc7ca2772f80e033bac20d1485bb26faf2eb09ed`)
- **Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)
- **Боевая база данных**: `<PRODUCTION_DB_METADATA>` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)
- **Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)
- **Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**

---

## 2. Реализация требований ТЗ-010 Редакции 1.1

### 2.1. Однозначность и причинная последовательность call_id (P0-O3, C4-01..C4-03, Scenarios A1..A3)
1. **Сценарий A1 (Повторное использование `call_id`)**:
   - При обнаружении дубликата `call_id` транскрипт бракуется со статусом `UNKNOWN` и ошибкой `AMBIGUOUS_TOOL_CALL_ID`.
   - Если действие записи не имеет верифицированного отдельного результата записи, статус `SUCCEEDED` категорически исключён.
2. **Сценарий A2 (Результат предшествует вызову)**:
   - В транскрипте шаг `TOOL_RESULT` не может физически предшествовать соответствующему `TOOL_CALL`.
   - Нарушение причинно-следственного порядка бракуется со статусом `UNKNOWN` и деталью `ORPHANED_TOOL_RESULT: TOOL_RESULT appeared before TOOL_CALL or orphaned`.
3. **Сценарий A3 (Конфликт идентификаторов сессии/задания)**:
   - Проверяются поля `job_id`, `session_id`, `task_id`, `rootConversationId`, `attempt_id`.
   - При расхождении между вызовом и ожидаемым заданием/сессией результат бракуется (`UNKNOWN`, `IDENTITY_CONFLICT_IN_TOOL_CALL` / `IDENTITY_CONFLICT_IN_TOOL_RESULT`).
4. **Взаимно однозначное сопоставление (1-to-1 matching)**:
   - События `write_file` и `edit_file` учитываются только при наличии строго одного валидного успешного `TOOL_RESULT` для уникального `call_id`.

### 2.2. Изоляция артефактов в границах каталога конкретного задания (P0-O5, C4-05)
1. **Выделенный корневой каталог задания**:
   - Метод `get_job_output_dir(job_id, attempt_id)` определяет выделенный изолированный путь `worktree/tests/output/<job_id>`.
2. **Фильтрация на этапе poll**:
   - Пути, содержащие ссылки на чужие попытки или задания (`other-job`, `other-attempt`), либо абсолютные пути вне выделенного каталога задания, немедленно помечаются `is_safe: False` с ошибкой `PATH_OUTSIDE_JOB_TEST_ROOT`.
   - Относительные пути резолвятся строго внутри каталога данного задания.
3. **Запрет пересечения заданий (Cross-Job Isolation)**:
   - В `_check_agent_session_status` артефакт обязан лежать строго внутри выделенного каталога `tests/output/<job_id>`.
   - Попытка Job A зачесть файл из папки Job B бракуется со статусом `TERMINAL_FAILURE` и деталью `UNSAFE_ARTIFACT_PATH`.

---

## 3. Результаты нативного воспроизведения сценариев (Replay Script)

Результаты запуска `scripts/replay_tz010_rev1_1_scenarios.py`:
- **Scenario A1 (Duplicate `call_id` reuse)**: `status=UNKNOWN`, `ok=False`, `detail=AMBIGUOUS_TOOL_CALL_ID` -> **PASS**
- **Scenario A2 (Result preceding call)**: `status=UNKNOWN`, `ok=False`, `detail=ORPHANED_TOOL_RESULT` -> **PASS**
- **Scenario A3 (Identity conflict)**: `status=UNKNOWN`, `ok=False`, `detail=IDENTITY_CONFLICT_IN_TOOL_CALL` -> **PASS**
- **Scenario C4-05 (Foreign Temp Attempt in poll)**: `is_safe=False`, `error=PATH_OUTSIDE_JOB_TEST_ROOT` -> **PASS**
- **Scenario Cross-Job Isolation**: `status=TERMINAL_FAILURE`, `ok=False`, `detail=UNSAFE_ARTIFACT_PATH` -> **PASS**
- **Scenario C4-08 (Positive CONTRACT_ONLY)**: `status=SUCCEEDED` -> **PASS**

---

## 4. Сводка полного набора автоматических тестов (122 / 122 PASS)

Команда запуска:
`python -m unittest tests/test_autostart_evidence_closure.py tests/test_autostart_provenance_and_permissions.py tests/test_autostart_dispatcher.py tests/test_drive_inbox_watcher.py tests/test_real_retrieval_shadow_pilot.py`

1. **`tests/test_autostart_evidence_closure.py`**: **13 / 13 PASS**
   - C4-01..C4-10 + Scenarios A1..A3, Foreign Attempt, Cross-Job Isolation
2. **`tests/test_autostart_provenance_and_permissions.py`**: **9 / 9 PASS**
   - S3-01..S3-10
3. **`tests/test_autostart_dispatcher.py`**: **12 / 12 PASS**
   - A4R-01..A4R-12
4. **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS**
   - Базовые сценарии монитора Google Drive
5. **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS**
   - 40 базовых контрактных + 10 NG + 10 G2 + 10 G3
- **ИТОГО**: **122 / 122 PASS (100%)** за 13.951 с.

---

## 5. Итоговые официальные статусы гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`CONTRACT_GATE_READY`** | **`GO`** | 70/70 контрактных тестов пройдены. |
| **`AUTOSTART_CODE_GATE`** | **`GO`** | Устранены оба замечания ТЗ-010 Rev 1.1: внедрена причинно-следственная проверка уникальности `call_id` (Scenarios A1..A3) и строгая изоляция каталогов артефактов конкретного задания (C4-05). Все 122 теста пройдены. |
| **`AUTOSTART_READY`** | **`BLOCKED_SETUP_REQUIRED`** | **Честный статус хоста**: на рабочей станции Acer под учётной записью `almax` отсутствует сконфигурированный контейнер изоляции (Windows AppContainer/Docker). Диспетчер надёжно блокирует запуск до настройки окружения оператором. |
| **`AUTOSTART_MODE`** | **`AUTO_EXECUTE_SCOPED`** | Активирован в конфигурации; строго ограничен верификацией границ. |
| **`LIVE_GATE`** | **`NOT_EXECUTED`** | На боевом Acer активен операторский стоп-маркер `watcher.pause`. |
| **`SESSION_RESTART_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Схема v2 и durable intent настроены в коде; реальный сбой daemon не симулировался. |
| **`WINDOWS_POWER_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | `StartWhenAvailable = true` включён в Task Scheduler; физический цикл сна не наблюдался. |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированная копия БД не создавалась. База `metadata.db` в режиме READ-ONLY (WAL: 0 байт). |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Сервер 8089 выключен. Проверка размерности модели не выполнялась. |
| **`EMBEDDING_PROFILE`** | **`UNVERIFIED`** | Профиль совместимости модели с LanceDB не подтверждён живым прогоном. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | Вызовов к боевому корпусу строго 0 (`actual_search_calls = 0`). |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |
