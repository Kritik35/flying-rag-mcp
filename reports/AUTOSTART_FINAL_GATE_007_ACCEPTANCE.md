# Stage 4.2.8 — AUTO-START-01 Final Integration Gate Acceptance Report (Revision 1.1)

**Документ**: Отчёт об устранении замечаний и интеграционной приёмке AUTO-START-01 (ТЗ `FR-TZ-20261117-007` / Редакция 1.1 от 2026-11-17)  
**ТЗ**: `FR-TZ-20261117-007` / Stage 4.2.8 / AUTO-START-01 FINAL INTEGRATION GATE / Редакция 1.1 от 2026-11-17  
**SHA-256 ТЗ**: `8af2015b63fe1e2262bf4b38cb9032203fa5c7b38a9e000314e5812fc7eb188c` (31,572 байт)  
**Локальный путь ТЗ**: `G:\Мой диск\FlyingRAG_TZ_Inbox\FR-TZ-20261117-007_REV1_1_AUTOSTART_VERIFIED_OUTCOME_7bd7f8784f97764ea405e3dfb75e41818cf27172.txt`  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: GO_PENDING_LIVE_CYCLE / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED**  
**Проверенный коммит кода (Phase A tested code anchor)**: [`2c9443b8ecfb80abef18073111e09c623eea38ce`](https://github.com/Kritik35/flying-rag-mcp/commit/2c9443b8ecfb80abef18073111e09c623eea38ce)  
**Tree SHA кода**: `a3ebf30849390ceff2db3c7bbd0b3e36094cb26c`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`4dcea739a2d0e50f891eee81b6a1dcee6fa70a8c`](https://github.com/Kritik35/flying-rag-mcp/commit/4dcea739a2d0e50f891eee81b6a1dcee6fa70a8c) (Tree: `4a8f197d28ca19f297e54b3fa0bfb11d4be17fbf`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`7bd7f8784f97764ea405e3dfb75e41818cf27172`](https://github.com/Kritik35/flying-rag-mcp/commit/7bd7f8784f97764ea405e3dfb75e41818cf27172) (Tree: `8d466ae287ce1dd554a652dfe68db6d17e344761`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**  

---

## 1. Исправление замечаний независимой проверки Rev 1.1

Во исполнение поручения оператора по ТЗ `FR-TZ-20261117-007 Rev 1.1` устранены фундаментальные недостатки верификации сессий, границ безопасности и управления очередью при сбоях лаунчера:

### 1.1. P0-B1: Полное устранение ложных терминальных успехов (R1–R8)
- **Проблема**: Метод `_check_agent_session_status()` допускал ложный `TERMINAL_SUCCESS` на вопросах агента («Начинаем?», R2), отказах в правах (`SOFT_DENIED`, R3), неполных хешах (R5), чужих сессиях (R4, R6) и без проверки реальных артефактов (R7), а также игнорировал битые хвосты JSONL (R8).
- **Исправление**:
  1. **Строгая корреляция (R4, R5, R6)**: Требуется полный 64-символьный SHA-256 или точный `job_id`. Совпадение только 12 символов префикса или наличие чужого хеша безусловно возвращает `UNKNOWN` (`TRANSCRIPT_CORRELATION_FAILED`). Проверяется совпадение `rootConversationId` с запрошенным `cid` (R6).
  2. **Устранение ложного старта (R1)**: Наличие только `USER_INPUT` в транскрипте возвращает `DISPATCH_CONFIRMED`, но ни в коем случае не `RUNNING` и не `SUCCEEDED`.
  3. **Блокировка вопросов подтверждения (R2)**: Вопросы агента («Начинаем?», «Приступать?», «Готов приступить», «Shall I proceed?») классифицируются как `WAITING_CONFIRMATION` и переводят worktree в карантин, не освобождая слот.
  4. **Учёт отказов инструментов (R3)**: Статусы `SOFT_DENIED`, `ERROR`, `FAILED`, `PERMISSION_DENIED` в `TOOL_RESULT` или заявления планировщика об отказе в правах возвращают `TERMINAL_FAILURE`.
  5. **Обязательная проверка артефактов (R7)**: Голое текстовое заявление «Task completed successfully» без выполненных шагов инструментов или без валидных артефактов приёмки возвращает `TERMINAL_FAILURE`. При наличии требуемых артефактов сверяется их размер (>0) и SHA-256.
  6. **Целостность журнала (R8)**: При наличии повреждённой/неполной строки в хвосте `transcript.jsonl` статус объявляется `UNKNOWN` (`INCONCLUSIVE_TRUNCATED_TRANSCRIPT`), аренда worktree не снимается.

#### Результаты нативного воспроизведения на Phase A (`scratch_replay.py`):
| Сценарий | Входные данные | Ожидаемый статус | Фактический статус на Phase A | Вердикт |
|:---|:---|:---:|:---:|:---:|
| **R1** | Только `USER_INPUT` с полным хешем | `DISPATCH_CONFIRMED` | `DISPATCH_CONFIRMED` (`SESSION_AWAITING_AGENT_START`) | **PASS** |
| **R2** | Ответ планировщика «Готов приступить. Начинаем?» | `WAITING_CONFIRMATION` | `WAITING_CONFIRMATION` (`AGENT_AWAITING_OPERATOR_CONFIRMATION`) | **PASS** |
| **R3** | `TOOL_RESULT(status=SOFT_DENIED)` + отказ | `TERMINAL_FAILURE` | `TERMINAL_FAILURE` (`TOOL_EXECUTION_DENIED_OR_FAILED`) | **PASS** |
| **R4** | Тот же task_id, но чужой полный 64-char хеш | `UNKNOWN` | `UNKNOWN` (`TRANSCRIPT_CORRELATION_FAILED`) | **PASS** |
| **R5** | Совпадают 12 символов, остальные 52 иные | `UNKNOWN` | `UNKNOWN` (`TRANSCRIPT_CORRELATION_FAILED`) | **PASS** |
| **R6** | Метаданные от чужого `rootConversationId` | `UNKNOWN` | `UNKNOWN` (`METADATA_CORRELATION_FAILED`) | **PASS** |
| **R7** | Только заявление без инструментов и артефактов | `TERMINAL_FAILURE` | `TERMINAL_FAILURE` (`UNVERIFIED_OUTCOME`) | **PASS** |
| **R8** | После ответа дописан неполный хвост JSONL | `UNKNOWN` | `UNKNOWN` (`INCONCLUSIVE_TRUNCATED_TRANSCRIPT`) | **PASS** |

---

### 1.2. P0-E1: Отказ от фиктивных профилей безопасности и fail-closed гейт
- **Проблема**: Профиль безопасности по умолчанию объявлялся `SAFE_WORKTREE_SCOPED` без проверки реального ограничения прав. Проверка сводилась к строковому сравнению `profile in ("SAFE_WORKTREE_SCOPED", "SANDBOX_ISOLATED")`.
- **Исправление**:
  1. Дефолтный профиль безопасности изменён на `UNVERIFIED`. Устранена маскировка переменной окружения через CLI argparse.
  2. Введён метод `verify_security_boundary()`: проверяет наличие физического файла `security_boundary.json` в `state_dir`, флаг `enforce_write_boundary=True`, и подтверждает отсутствие запрещённых путей (`C:\RAG_Acer\data_imported\metadata.db`, `C:\RAG_Acer\repos\flying-rag-mcp`) среди `allowed_write_roots`.
  3. При недоказанном профиле диспетчер возвращает `BLOCKED_SETUP_REQUIRED` и выполняет **СТРОГО 0** вызовов runner.
  4. В prompt лаунчера передаются: `task_id`, `job_id`, `revision`, полный 64-символьный `sha256`, ожидаемый `worktree_dir` и путь к спулу.

---

### 1.3. P0-C1: Карантин worktree при неопределённом исходе лаунчера и durable intent
- **Проблема**: Карантин покрывал только уже сохранённую сессию с `conversation_id`. При таймауте лаунчера (`TimeoutExpired` / exit 124), пустом выводе или потере ID диспетчер выставлял `FAILED` и `active_execution = None`, освобождая worktree для следующей задачи при потенциально работающем в фоне агенте.
- **Исправление**:
  1. **Durable Intent**: До любого внешнего вызова в `state["active_execution"]` атомарно записывается `status="DISPATCHING_INTENT"`.
  2. **Worktree Quarantine upon Uncertainty**: При таймауте (exit 124), пустом выводе лаунчера, неразбираемом ответе или отсутствии `conversationId` задача переводится в `WORKTREE_QUARANTINED`, `active["quarantine"] = True` и `active["status"] = "DISPATCH_UNKNOWN_QUARANTINE"`. Слот worktree не освобождается, любые последующие задачи в очереди блокируются.
  3. **Crash Recovery**: При запуске/перезагрузке диспетчера обнаружение незавершённого `DISPATCHING_INTENT` или задачи в состоянии `DISPATCHING` без валидной сессии автоматически переводит worktree в карантин.

---

## 2. Результаты расширенной матрицы проверок A4R-01 .. A4R-12

| Код | Приоритет | Наименование проверки | Ожидаемый результат | Фактический результат | Корпус вызовы | Вердикт |
|:---:|:---:|:---|:---|:---|:---:|:---:|
| **`A4R-01`** | P0 | Недоказанный профиль прав (дефолт, env=UNPROVEN, отсутствие boundary config) | `BLOCKED_SETUP_REQUIRED` во всех 4 случаях; строго 0 вызовов runner | `BLOCKED_SETUP_REQUIRED`, 0 вызовов runner; exit 126 на `_invoke_external_runner` | 0 | **PASS** |
| **`A4R-02`** | P0 | Проверенная граница безопасности и запрет боевых корней | Разрешённый контур пропускает запуск; наличие боевой базы данных в allowed roots блокирует запуск | Разрешённый контур -> запуск (1 вызов); боевой корень -> `BLOCKED_SETUP_REQUIRED` (0 вызовов) | 0 | **PASS** |
| **`A4R-03`** | P0 | Metadata-only и USER_INPUT-only в транскрипте | Статус строго `DISPATCH_CONFIRMED`; ни `RUNNING`, ни `SUCCEEDED` | `DISPATCH_CONFIRMED` во всех случаях, `outcome_verified=False` | 0 | **PASS** |
| **`A4R-04`** | P0 | «Начинаем?», SOFT_DENIED, отказ, отсутствующий артефакт | `WAITING_CONFIRMATION` -> карантин; `SOFT_DENIED` / отказ / нет артефакта -> `TERMINAL_FAILURE` | Все сценарии отказа подтверждены; worktree блокируется в карантине | 0 | **PASS** |
| **`A4R-05`** | P0 | Чужой хеш, префикс 12 символов, чужой rootId, спуф | Безусловный возврат `UNKNOWN` (`TRANSCRIPT_CORRELATION_FAILED`); 0 ложных успехов | Все попытки некорректной корреляции и спуфинга отклонены со статусом `UNKNOWN` | 0 | **PASS** |
| **`A4R-06`** | P0 | Подтверждённый terminal outcome против подмены артефакта | Полный хеш + шаги + терминал + артефакт -> `TERMINAL_SUCCESS`; подмена байт -> `TERMINAL_FAILURE` | Валидный артефакт -> `TERMINAL_SUCCESS`; подменённый хеш артефакта -> `TERMINAL_FAILURE` | 0 | **PASS** |
| **`A4R-07`** | P0 | Обрыв/битый хвост JSONL после ответа планировщика | Возврат `UNKNOWN` (`INCONCLUSIVE_TRUNCATED_TRANSCRIPT`); worktree не освобождается | Битый хвост строки 4 перехватывается, аренда worktree не освобождается | 0 | **PASS** |
| **`A4R-08`** | P0 | Таймаут/неопределённость лаунчера (2 задачи в очереди) | Первая задача -> `WORKTREE_QUARANTINED`; вторая задача НЕ запускается (0 вызовов) | Карантин сохранён, вызовы для задачи 2 = 0; карантин переживает перезапуск | 0 | **PASS** |
| **`A4R-09`** | P0 | Durable intent перед запуском и восстановление сбоя | Intent сохранён на диск до вызова runner; сбой mid-intent -> автокарантин при старте | `DISPATCHING_INTENT` зафиксирован на диске; сбой восстановлен как карантин (0 запусков) | 0 | **PASS** |
| **`A4R-10`** | P0 | Регрессионный пакет: CLI, tuple ordering, conflict, veto | CLI `--poll-once`/`--bootstrap` без ошибок; `(3, 10) > (3, 9)`; карантин конфликта; вето маркеров | Все регрессионные тесты пройдены без ошибок | 0 | **PASS** |
| **`A4R-11`** | P1 | Разделение контрактов и живого цикла безопасности | При наличии `watcher.pause` -> `PAUSED` (0 вызовов); при `UNVERIFIED` -> `BLOCKED` (0 вызовов) | Fail-closed подтверждён; контрактные моки не дают статус `LIVE_OBSERVED`; `LIVE_GATE: NOT_EXECUTED` | 0 | **PASS** |
| **`A4R-12`** | P1 | Согласованность отчёта и `effective_dispatch_state` | `get_status_report()` отражает паузу, карантин, границы; планировщик -> `CONFIGURED_UNOBSERVED` | Состояния согласованы; статус по питанию честно зафиксирован `CONFIGURED_UNOBSERVED` | 0 | **PASS** |

---

## 3. Сводка выполнения тестов (112 / 112 PASS)

- **`tests/test_autostart_dispatcher.py`**: **24 / 24 PASS** (7.684 с)  
  - 12 основных тестов матрицы A4R-01..A4R-12
  - 12 тестов обратной совместимости и регрессий A4-01..A4-12
- **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS** (1.031 с)  
- **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS** (12.360 с)  
  - Базовые контрактные тесты Stage 4.2.8: 40
  - Негативные тесты Revision 1 (NG-01..NG-10): 10
  - Негативные тесты Revision 2 (G2-01..G2-10): 10
  - Негативные тесты Revision 3 & 3.2 (G3-01..G3-10): 10
- **Итого**: **112 / 112 PASS (100%)**

---

## 4. Итоговые официальные статусы гейтов

- **`CONTRACT_GATE_READY`**: **`GO`** (70/70 контрактных тестов пройдены)
- **`AUTOSTART_CODE_GATE`**: **`GO`** (все P0-дефекты устранены, fail-closed поведение и регрессионная матрица A4R-01..A4R-12 полностью подтверждены)
- **`AUTOSTART_READY`**: **`GO_PENDING_LIVE_CYCLE`** (ожидает подтверждённого прогона через Task Scheduler при наличии разрешённого runtime)
- **`AUTOSTART_MODE`**: **`AUTO_EXECUTE_SCOPED`**
- **`LIVE_GATE`**: **`NOT_EXECUTED`** (на боевом Acer активен операторский `watcher.pause`)
- **`SESSION_RESTART_RECOVERY`**: **`CONFIGURED_UNOBSERVED`**
- **`WINDOWS_POWER_RECOVERY`**: **`CONFIGURED_UNOBSERVED`**
- **`REAL_CORPUS_PILOT`**: **`NOT_EXECUTED`** (`actual_search_calls = 0`)
- **`SNAPSHOT_READY`**: **`NO_GO`** (боевая БД в режиме READ-ONLY, WAL: 0 байт)
- **`PRODUCTION_DEPLOYMENT`**: **`NOT_AUTHORIZED`** (боевой репозиторий на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`)
