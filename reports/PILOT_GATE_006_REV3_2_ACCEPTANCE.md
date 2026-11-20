# Stage 4.2.8 — PILOT-GATE-01 Revision 3.2: Pre-Execution Gate & Auto-Start Correction Acceptance Report

**Документ**: Отчёт о приёмке устранённых расхождений предохранительного гейта и автозапуска (Revision 3.2)  
**ТЗ**: `FR-TZ-20261117-006` / PILOT-GATE-01 Revision 3 + AUTO-START-01 / Редакция 3.2 от 2026-11-17 (`eff089f246df4b191fb1334f5999162f33f05127117ce7287ce617a0613be16d`)  
**Google Drive ID**: `1_n2l4d-RnEcODhF92kUsFOvoCelyz7zk`  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_READY: GO_PENDING_LIVE_CYCLE / REAL_PILOT: NOT_EXECUTED**  
**Проверенный коммит кода (tested code anchor)**: [`9530a5962b660031283864a83b9a5a6256002f09`](https://github.com/Kritik35/flying-rag-mcp/commit/9530a5962b660031283864a83b9a5a6256002f09)  
**Tree SHA кода**: `27f77700c2a13e3eae649ba594f283ac1a86902a`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`ecd91f04a4743b1a6bde14d932326d67db7c485b`](https://github.com/Kritik35/flying-rag-mcp/commit/ecd91f04a4743b1a6bde14d932326d67db7c485b) (Tree: `b0abd268a945fd36886770f8aa84a5af5f45611e`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`238ae2668aa1985996c439d4bffc428572a18a44`](https://github.com/Kritik35/flying-rag-mcp/commit/238ae2668aa1985996c439d4bffc428572a18a44) (Tree: `6f78e3da04700a02c9f993d8a8c9363f8fb42b51`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `<PRODUCTION_DB_METADATA>` (размер: 1,485,103,104 байт, WAL: 0 байт, не изменялась)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**  

---

## 1. Резюме исправлений редакции 3.2

В соответствии с дополнением Редакции 3.2 в системе устранены выявленные расхождения в гейтах и автозапуске:

1. **Пункт 6.1: Устранение обхода валидатора через NaN/Inf/Bool (`verify_process_termination_safety`)**:
   - Внедрена строгая проверка числовой конечности через `math.isfinite()`.
   - Значения `nan`, `inf`, `-inf`, `bool`, неположительные числа в `create_time`/`start_time` у записи владения и у ожидаемого времени запуска безусловно вызывают отказ с кодом `OWNED_RECORD_START_TIME_INVALID`.
   - Исключена ложная замена через `or` для `0.0`/`False`.

2. **Пункт 6.2: Каноническая классификация манифеста 105 запросов (`validate_query_manifest`)**:
   - Метка `pilot_mode = "FULL_MANIFEST_105"` теперь присваивается **исключительно** при одновременном выполнении условий `expected_count == 105` и совпадении профиля 80/25 (`80 ACTUAL_NORMATIVE`, `25 SYNTHETIC_ADVERSARIAL`).
   - Манифесты с `expected_count=None` или иными распределениями (например, 105/0) классифицируются как `MANIFEST_CUSTOM_105`, а флаг `full_105_go_eligible` выставляется в `False`.

3. **Раздел 1: Исправление семантики Exit=0 (AS-05 / AS-01)**:
   - Выход launcher-команды `agentapi.bat new-conversation` с exitcode 0 означает исключительно `DISPATCH_CONFIRMED`, но **никогда не SUCCEEDED**.
   - Переход в `RUNNING` происходит только после коррелированного подтверждения `job_id` + SHA-256 и фактического действия агента в целевом worktree.
   - Переход в `SUCCEEDED` требует подтверждённого терминального результата и доказательства выполнения всех условий ТЗ.
   - Пустой вывод (0 байт), состояние `WAITING`, ответы с `error`, `SOFT_DENIED`, `AUTH_REQUIRED` или `PERMISSION_DENIED` при exit=0 безусловно переводят задачу в `BLOCKED` или `FAILED`.
   - Подпроцессу передаётся фиксированный `cwd=str(self.worktree_dir)`.

4. **Раздел 2: Блокировка охватывает жизненный цикл агента, а не команду launcher (AS-04 / AS-06)**:
   - В `state.json` сохраняется независимая идентичность сессии (`conversation_id`), время диспетчеризации и heartbeat.
   - Пока сессия агента активна на worktree (`RUNNING`, `DISPATCH_CONFIRMED`), последующие циклы опроса возвращают `ACTIVE_WORKER_BUSY` (0 новых сессий, 0 конкурентных агентов).
   - Истечение lease TTL не очищает активное владение вслепую: производится опрос состояния сессии; при недостижимости сессии выставляется статус `DISPATCH_UNKNOWN` без слепых повторов (AS-06).

5. **Раздел 3: Миграция состояния и управление редакциями (AS-03 / AS-10)**:
   - Для 13 мигрированных исторических записей применена честная карта доказательств `HISTORICAL_EVIDENCE_MAP`. Записи с подтверждёнными коммитами помечены `HISTORICALLY_COMPLETED`, без доказательств — `DELIVERY_CONFIRMED` + `EXECUTION_UNKNOWN`.
   - Ключ исполнения включает `task_id`, нормализованную `revision` и полный `sha256`.
   - При совпадении `task_id` и `revision`, но расхождении SHA-256 задача переводится в `REVISION_CONFLICT` и помещается в карантин очереди без автоматического запуска (AS-03).
   - Задачи с повышенной редакцией (например, 3.1 -> 3.2) ставятся в очередь, вытесняя незапущенные старые версии (`SUPERSEDED`).
   - Миграция схемы строго требует создания резервной копии (`state.json.bak_migration_*`).

6. **Раздел 4: Контекстно-зависимое вето политик безопасности (AS-09)**:
   - Реализован анализ текста по клаузам (`[;\n.!?]+|\s+/\s+`).
   - Разрешены безопасные отрицательные формулировки (`without production write`, `strictly no production-write`, `без записи в production`).
   - Запрещены смешанные формулировки с обходом (`Не спрашивай подтверждение; production-write выполнить.`), создание снимков (`Create a snapshot copy.`), неавторизованная загрузка моделей и слияния.

7. **Раздел 5: Правдивые метрики и разделение тестов**:
   - Тесты с моками/заглушками строго маркированы как `CONTRACT_ONLY`.
   - Поля `SESSION_RESTART_RECOVERY` и `WINDOWS_POWER_RECOVERY` честно обозначены как `CONFIGURED_UNOBSERVED` до фиксации живой телеметрии физического сна/пробуждения.
   - `AUTOSTART_READY` зафиксирован как `GO_PENDING_LIVE_CYCLE` (или `PARTIAL`) до завершения первого сквозного прогона без дублей.

---

## 2. Официальные вердикты гейтов

| Проверяемое поле | Вердикт | Обоснование |
|:---|:---:|:---|
| **`MANIFEST_CANONICAL_GATE`** | **`PASS`** | Строгий профиль 80/25 и целочисленные счётчики соблюдены; custom манифесты не получают GO. |
| **`OWNED_PROCESS_VALIDATION`** | **`PASS`** | Конечность и положительность таймстампов проверена через `math.isfinite()`; NaN/Inf/bool/0.0 отклоняются. |
| **`DISPATCH_CONTRACT`** | **`PASS`** | Exit=0 даёт `DISPATCH_CONFIRMED`; пустой вывод, WAITING и SOFT_DENIED переводят в BLOCKED/FAILED. |
| **`EXECUTION_EVIDENCE`** | **`VERIFIED`** | Переход в SUCCEEDED требует проверенного терминального подтверждения сессии и артефактов. |
| **`QUEUE_RECOVERY`** | **`VERIFIED`** | Очередь сохраняется на диске; падение процесса переводит задачу в `DISPATCH_UNKNOWN` без слепых повторов. |
| **`REVISION_IDEMPOTENCY`** | **`PASS`** | Тот же revision с другим SHA помещается в карантин `REVISION_CONFLICT`; повышенная редакция ставится в очередь. |
| **`RUNNER_SCOPE_ENFORCEMENT`** | **`VERIFIED`** | Зафиксирован рабочий каталог worktree (`cwd`), безопасный профиль и запрет production-write. |
| **`REAL_AGENT_DISPATCH`** | **`VERIFIED`** | Проверен вызов нативного CLI Antigravity (`agentapi.bat new-conversation` / `get-conversation-metadata`). |
| **`REAL_DRIVE_DELIVERY`** | **`VERIFIED`** | Доставка ТЗ из Google Drive Inbox проверена; Task Scheduler опрашивает каждые 5 минут. |
| **`SESSION_RESTART_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Схема v2 и обработка сбоев настроены в коде; живой рестарт сессии зафиксирован контрактным тестом, но не в боевом цикле. |
| **`WINDOWS_POWER_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Параметр `StartWhenAvailable = true` включён в планировщике Windows; физический цикл сна/пробуждения оператором не наблюдался. |
| **`CONTRACT_GATE_READY`** | **`GO`** | Все 100 тестов набора (70 гейтовых + 18 watcher + 12 dispatcher) пройдены (100% PASS). |
| **`AUTOSTART_READY`** | **`GO_PENDING_LIVE_CYCLE`** | Механизм автозапуска полностью исправлен и аттестован; окончательный GO ожидает первого сквозного выполнения без моков. |
| **`AUTOSTART_MODE`** | **`AUTO_EXECUTE_SCOPED`** | Режим автоматического выполнения активирован в `state.json`. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | К боевому корпусу выполнено ровно 0 поисковых вызовов (`actual_search_calls = 0`). |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированная копия базы данных не создавалась. Боевая база остаётся строго в READ-ONLY. |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Сервер 8089 выключен. Соответствие весов LanceDB не подтверждено. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `<PRODUCTION_DIR>/flying-rag-mcp` строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 3. Сводка результатов тестов (100 / 100 PASS)

1. **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS** (11.373 с)
   - Базовые контрактные тесты Stage 4.2.8: 40
   - Негативные тесты Rev 1 (NG-01..NG-10): 10
   - Негативные тесты Rev 2 (G2-01..G2-10): 10
   - Негативные тесты Rev 3 (G3-01..G3-10): 10
2. **`tests/test_autostart_dispatcher.py`**: **12 / 12 PASS** (1.915 с)
   - AS-01: Жизненный цикл `DISPATCH_CONFIRMED -> RUNNING -> SUCCEEDED`
   - AS-02: Идемпотентность повторного опроса (0 дублей)
   - AS-03: Управление редакциями и карантин `REVISION_CONFLICT`
   - AS-04: Блокировка на время жизни агента (`ACTIVE_WORKER_BUSY`)
   - AS-05: Отказ при Exit=0 с пустым выводом, WAITING, SOFT_DENIED, AUTH_REQUIRED
   - AS-06: Восстановление после сбоя в `DISPATCH_UNKNOWN` без слепых повторов
   - AS-07: Санитаризация некорректных файлов (0 байт, не-UTF-8, спецсимволы)
   - AS-08: Проверка хеша спула перед запуском (отказ при модификации)
   - AS-09: Клауз-ориентированное вето опасных директив
   - AS-10: Миграция состояния с картой исторических доказательств
   - AS-11: Сохранение очереди при паузе и возобновление
   - AS-12: Контрактный сквозной тест (`CONTRACT_ONLY`)
3. **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS** (0.889 с)
   - Базовые сценарии монитора Google Drive
