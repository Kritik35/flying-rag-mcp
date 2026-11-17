# Stage 4.2.8 — AUTO-START-01 Final Integration Gate Acceptance Report

**Документ**: Отчёт об устранении замечаний и интеграционной приёмке AUTO-START-01 (ТЗ `FR-TZ-20261117-007` / Редакция 1.0 от 2026-11-17)  
**ТЗ**: `FR-TZ-20261117-007` / Stage 4.2.8 / AUTO-START-01 FINAL INTEGRATION GATE / Редакция 1.0 от 2026-11-17  
**SHA-256 ТЗ**: `300bf553633220b03f0a3068943982270bb4222e7fc36ebd0a227b9154d7ece5` (24,120 байт)  
**Локальный путь ТЗ**: `G:\Мой диск\FlyingRAG_TZ_Inbox\FR-TZ-20261117-007_AUTOSTART_FINAL_GATE_9530a5962b660031283864a83b9a5a6256002f09.txt`  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: GO_PENDING_LIVE_CYCLE / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED**  
**Проверенный коммит кода (Phase A tested code anchor)**: [`7bd7f8784f97764ea405e3dfb75e41818cf27172`](https://github.com/Kritik35/flying-rag-mcp/commit/7bd7f8784f97764ea405e3dfb75e41818cf27172)  
**Tree SHA кода**: `8d466ae287ce1dd554a652dfe68db6d17e344761`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`27507fb98bedc2042fc848b1d4ad53bae41e65ee`](https://github.com/Kritik35/flying-rag-mcp/commit/27507fb98bedc2042fc848b1d4ad53bae41e65ee) (Tree: `dd1578b69078020b4ddbd9b79c3c1d7f80ac1f8f`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`9530a5962b660031283864a83b9a5a6256002f09`](https://github.com/Kritik35/flying-rag-mcp/commit/9530a5962b660031283864a83b9a5a6256002f09) (Tree: `27f77700c2a13e3eae649ba594f283ac1a86902a`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**  

---

## 1. Исправление замечаний P0-A .. P0-E

Во исполнение прямого поручения оператора по ТЗ `FR-TZ-20261117-007` устранены 5 критических дефектов автоматического диспетчера:

### P0-A: Устранение NameError в CLI планировщика
- **Проблема**: В `main()` вызов `watcher.run_locked_cycle(bootstrap=bootstrap)` адресовал необъявленную локальную переменную `bootstrap` вместо `args.bootstrap`, что приводило к `NameError` при штатном запуске из Windows Task Scheduler с флагом `--poll-once`.
- **Исправление**: В `scripts/drive_inbox_watcher.py` строка 1510 изменена на `res = watcher.run_locked_cycle(bootstrap=args.bootstrap)`. Добавлены аргументы `--brain-dir` и `--security-profile`.
- **Верификация**: Реальный subprocess-прогон `python scripts/drive_inbox_watcher.py --poll-once` на чистом temp inbox завершается с exit code 0, чистым stderr (0 байт), валидным JSON и 0 вызовов runner.

### P0-B: Верификация терминальных результатов сессий
- **Проблема**: Штатный checker `_check_agent_session_status()` опирался исключительно на `get-conversation-metadata`, возвращая `RUNNING` при наличии `rootConversationId` или `createdAt`. Завершённая сессия сохраняет эти поля, из-за чего статус никогда не переходил в `SUCCEEDED` на реальном протоколе, а подмена квитанции диспетчером не блокировалась.
- **Исправление**: Реализован двухуровневый инспектор:
  1. `get-conversation-metadata` с полями `rootConversationId`/`createdAt` без записей в журнале транскрипта транслируется строго в `DISPATCH_CONFIRMED`, но не `RUNNING` и не `SUCCEEDED`.
  2. Инспектор журнала транскрипта (`transcript.jsonl`) сопоставляет `job_id`, `sha256` и `task_id`. Переход в `RUNNING` подтверждается только при наблюдении начатых действий агента; переход в `TERMINAL_SUCCESS` — только при обнаружении завершающего ответа планировщика (`PLANNER_RESPONSE` без ожидающих tool calls). Самодельные или спуфленные квитанции (`WATCHER_SELF_AUTHORED_RECEIPT`) безусловно отклоняются (`UNKNOWN`).

### P0-C: Блокирующий карантин worktree при неопределённой сессии (UNKNOWN)
- **Проблема**: При статусе сессии `UNKNOWN` прежний код сбрасывал `active_execution = None`, что позволяло диспетчеру выбрать следующую задачу из очереди и запустить её в то же самое worktree, создавая риск гонок и разрушения состояния.
- **Исправление**: При статусе сессии `UNKNOWN` диспетчер сохраняет владение worktree: выставляется `active["quarantine"] = True` и `active["status"] = "DISPATCH_UNKNOWN_QUARANTINE"`. Метод `dispatch_queue()` немедленно возвращает `WORKTREE_QUARANTINED`, блокируя ВСЕ последующие запуски из очереди до ручной реконсилиации оператора.

### P0-D: Приоритет заголовков редакций и сравнение по tuple
- **Проблема**: Регулярное выражение искало первую подстроку `Revision 3`, игнорируя строку `Редакция документа: 3.1`. Сравнение редакций как `float` приводило к ложному `3.10 < 3.9`.
- **Исправление**: В `extract_task_identity()` установлен нормативный порядок приоритетов:
  1. Явное поле `Редакция документа: X.Y` в шапке (строки 1–6).
  2. Поле `Редакция: X.Y` в шапке.
  3. Номер `Revision X` из названия.
  4. Постфикс `REV*` в имени файла.
  При расхождении мажорных номеров возвращается `REVISION_IDENTITY_CONFLICT`. Редакции преобразуются функцией `parse_revision_tuple()` в целочисленные кортежи (`(3, 10) > (3, 9)`), корректно вытесняя устаревшие задачи (`SUPERSEDED`).

### P0-E: Ограничение прав runner и устранение обхода через маркеры аудита
- **Проблема**: Передача `cwd=worktree` не ограничивала полномочия процесса учетной записи. Фильтр `check_policy_veto()` удалял строки с маркерами `-> allowed`, что создавало дыру безопасности при внедрении директив вида `do production-write -> allowed`.
- **Исправление**:
  1. Удалено вырезание строк `clean_lines` — директивы с маркерами аудита теперь проверяются наравне с обычными и безусловно вызывают вето (`POLICY_VETO`).
  2. Исправлен double-space баг в регулярном выражении отрицаний (`не` без глагола).
  3. Введён строгий гейт профиля прав: при недоказанном или небезопасном профиле (`UNPROVEN_HOST_PERMISSIONS`) диспетчер выставляет `BLOCKED_SETUP_REQUIRED` и выполняет строго 0 вызовов агента.

---

## 2. Результаты обязательной матрицы проверок A4-01 .. A4-12

| Код | Приоритет | Наименование проверки | Ожидаемый результат | Фактический результат | Вердикт |
|:---:|:---:|:---|:---|:---|:---:|
| **`A4-01`** | P0 | Запуск watcher CLI через реальный Python subprocess | Exit code 0, валидный JSON, нет NameError, 0 agent calls. Повторный `--poll-once` идемпотентен | Subprocess завершился с exit 0, NameError отсутствует, JSON валиден, 0 вызовов | **PASS** |
| **`A4-02`** | P0 | `get-conversation-metadata` без транскрипта | Статус строго `DISPATCH_CONFIRMED`, ни `RUNNING`, ни `SUCCEEDED` | Сессия признана созданной, но статус остался `DISPATCH_CONFIRMED` | **PASS** |
| **`A4-03`** | P0 | Верификация действий и терминального ответа | При наличии шагов -> `RUNNING`; при терминальном `PLANNER_RESPONSE` -> `SUCCEEDED`; спуфинг -> отказ | Все 4 сценария подтверждены: шаги -> RUNNING, терминал -> SUCCEEDED, чужой хеш -> отказ, спуф -> отказ | **PASS** |
| **`A4-04`** | P0 | Карантин worktree при неизвестной сессии | Статус сессии `UNKNOWN` переводит worktree в карантин; вторая задача НЕ запускается | `WORKTREE_QUARANTINED`, `active_execution` сохранён, 0 вызовов для задачи 2 | **PASS** |
| **`A4-05`** | P0 | Нормативный приоритет заголовков редакций | `Revision 3` + `Редакция: 3.1` -> 3.1; при 3.2 -> 3.2; in-place обновление вытесняет старую задачу | 3.1 и 3.2 извлечены корректно; задача 3.1 переведена в `SUPERSEDED` без конфликта | **PASS** |
| **`A4-06`** | P0 | Сравнение редакций кортежами и карантин конфликта | `(3, 10) > (3, 9)`; одинаковый task+rev с другим SHA -> `REVISION_CONFLICT` (0 запусков) | `(3, 10) > (3, 9)` подтверждено; конфликтный хеш заблокирован в очереди (0 запусков) | **PASS** |
| **`A4-07`** | P0 | Запрет обхода через аудит-маркеры | Отрицания разрешены; директивы вида `do production-write -> allowed` ветируются | Строго 0 опасных операций; попытка обхода с маркером аудита заблокирована вето | **PASS** |
| **`A4-08`** | P0 | Недоказанный профиль прав runner | Недоказанный профиль -> `BLOCKED_SETUP_REQUIRED` (0 вызовов); безопасный профиль -> запуск | `BLOCKED_SETUP_REQUIRED` при `UNPROVEN_HOST_PERMISSIONS` (0 вызовов runner) | **PASS** |
| **`A4-09`** | P0 | Ошибки при Exit=0 (пустой stdout, WAITING, SOFT_DENIED) | Отказ со статусом `BLOCKED` или `FAILED`, никогда не `SUCCEEDED`, 0 слепых повторов | Все 5 сценариев сбоя подтверждены: задачи заблокированы без потери очереди | **PASS** |
| **`A4-10`** | P1 | Историческая карта доказательств | Задачи с подтверждённым коммитом -> `HISTORICALLY_COMPLETED`; без доказательств -> `EXECUTION_UNKNOWN` | 13 исторических задач размечены по коммитам; неподтверждённые остались `EXECUTION_UNKNOWN` | **PASS** |
| **`A4-11`** | P1 | Разделение контрактных и живых тестов | Контрактные тесты явно маркируются `CONTRACT_ONLY` и не выдаются за `LIVE_OBSERVED` | Контрактные утверждения подтверждены; статус остаётся `CONTRACT_ONLY` | **PASS** |
| **`A4-12`** | P1 | Честный статус восстановления по питанию | `StartWhenAvailable` без физической телеметрии -> `CONFIGURED_UNOBSERVED`, не `OBSERVED` | Статус `CONFIGURED_UNOBSERVED` зафиксирован в отчёте | **PASS** |

---

## 3. Сводка выполнения тестов

- **Тестовый набор**: `tests/test_autostart_dispatcher.py` (A4-01..A4-12)
- **Результат**: **12 / 12 PASS (100%)**
- **Ошибок**: **0**
- **Провалов**: **0**
- **Время выполнения**: 3.058 с

Полный набор тестов проекта:
- `tests/test_real_retrieval_shadow_pilot.py`: **70 / 70 PASS** (11.753 с)
- `tests/test_drive_inbox_watcher.py`: **18 / 18 PASS** (1.003 с)
- `tests/test_autostart_dispatcher.py`: **12 / 12 PASS** (3.058 с)
- **Итого**: **100 / 100 PASS (100%)**

---

## 4. Итоговые статусы гейтов

- **`CONTRACT_GATE_READY`**: **`GO`** (70/70 контрактных тестов пройдены)
- **`AUTOSTART_CODE_GATE`**: **`GO`** (12/12 тестов A4-01..A4-12 пройдены, CLI NameError устранён)
- **`AUTOSTART_READY`**: **`GO_PENDING_LIVE_CYCLE`** (ожидает живого цикла AS-12 в Task Scheduler)
- **`AUTOSTART_MODE`**: **`AUTO_EXECUTE_SCOPED`**
- **`SESSION_RESTART_RECOVERY`**: **`CONFIGURED_UNOBSERVED`**
- **`WINDOWS_POWER_RECOVERY`**: **`CONFIGURED_UNOBSERVED`**
- **`REAL_CORPUS_PILOT`**: **`NOT_EXECUTED`** (`actual_search_calls = 0`)
- **`SNAPSHOT_READY`**: **`NO_GO`**
- **`MODEL_INDEX_IDENTITY`**: **`UNVERIFIED`**
- **`PRODUCTION_DEPLOYMENT`**: **`NOT_AUTHORIZED`**
