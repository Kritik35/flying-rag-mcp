# Stage 4.2.8 — AUTO-START-01 Final Integration Gate Acceptance Report (Revision 1.2)

**Документ**: Отчёт об устранении замечаний и интеграционной приёмке AUTO-START-01 (ТЗ `FR-TZ-20261117-007` / Редакция 1.2 от 2026-11-17)  
**ТЗ**: `FR-TZ-20261117-007` / Stage 4.2.8 / AUTO-START-01 FINAL INTEGRATION GATE / Редакция 1.2 от 2026-11-17  
**SHA-256 ТЗ**: `0efbcddbe72a39bf32f0b5f6939c4b3ae4a4528fcf65138b94f956fc172c81f3` (17,637 байт)  
**Локальный путь ТЗ**: `G:\Мой диск\FlyingRAG_TZ_Inbox\FR-TZ-20261117-007_REV1_2_OUTCOME_BOUNDARY_2c9443b8_3dc6b8dd.txt`  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: GO_PENDING_LIVE_CYCLE / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED**  
**Проверенный коммит кода (Phase A tested code anchor)**: [`3a63ed72f5bdca2849d28edaa08e0894daa1d1b1`](https://github.com/Kritik35/flying-rag-mcp/commit/3a63ed72f5bdca2849d28edaa08e0894daa1d1b1)  
**Tree SHA кода**: `a4902418d62ae11b9c81f2b2c00f2c5cbf8652a0`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`3dc6b8dd4556edd503fc98106acb458c56da86e0`](https://github.com/Kritik35/flying-rag-mcp/commit/3dc6b8dd4556edd503fc98106acb458c56da86e0) (Tree: `33129af0a50beaca79d0759c7c4ae5662ca3ba37`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`2c9443b8ecfb80abef18073111e09c623eea38ce`](https://github.com/Kritik35/flying-rag-mcp/commit/2c9443b8ecfb80abef18073111e09c623eea38ce) (Tree: `a3ebf30849390ceff2db3c7bbd0b3e36094cb26c`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**  

---

## 1. Исправление замечаний независимой проверки Rev 1.2

Во исполнение адресного дополнения ТЗ `FR-TZ-20261117-007 Rev 1.2` устранены оставшиеся два фундаментальных разрыва: **P0-E1** (доказательство ограничения прав вместо самодекларации) и **P0-B1** (фактически выполненное действие инструмента вместо намерения):

### 1.1. P0-E1: Доказательство реального ограничения прав (E-1 .. E-3)
- **Проблема**: Прежняя проверка `verify_security_boundary()` считала достаточным наличие JSON-файла `{"enforce_write_boundary": true}` даже с пустым списком `allowed_write_roots`, что являлось самодекларацией без реального рантайм-ограничения прав.
- **Исправление**:
  1. **E-1**: Проверяется, что `allowed_write_roots` существует, является списком и содержит не менее одного разрешённого пути. При пустом списке возвращается `BLOCKED_SETUP_REQUIRED`.
  2. **E-2**: Требуется обязательное подтверждение активного рантайм-провайдера изоляции (`runtime_isolation_type` != `NONE`/`UNVERIFIED`) и наличие токена аттестации (`isolation_attestation_token`). При их отсутствии возвращается `BLOCKED_SETUP_REQUIRED`, лаунчер блокируется и выполняется **СТРОГО 0** вызовов.
  3. **E-3**: Только при наличии непустых разрешённых корней, отсутствии пересечений с запрещёнными корнями (`metadata.db`, `repo`) и наличии валидного рантайм-токена аттестации возвращается `SECURITY_BOUNDARY_VERIFIED`.
  4. На боевом хосте Acer (пользователь `almax` без настроенного OS-контейнера/песочницы) система честно возвращает `BLOCKED_SETUP_REQUIRED`, предотвращая неконтролируемый запуск.

#### Результаты нативного воспроизведения P0-E1:
| Тест | Конфигурация | Ожидаемый результат | Фактический результат на Phase A | Вердикт |
|:---:|:---|:---:|:---:|:---:|
| **E-1** | `allowed_write_roots: []` (пустой список) | `BLOCKED_SETUP_REQUIRED` (0 вызовов) | `(False, 'BLOCKED_SETUP_REQUIRED: allowed_write_roots is missing or empty (E-1)')` | **PASS** |
| **E-2** | Непустые корни, но `runtime_isolation_type: NONE` | `BLOCKED_SETUP_REQUIRED` (0 вызовов) | `(False, 'BLOCKED_SETUP_REQUIRED: No active runtime isolation provider confirmed (E-2)...')` | **PASS** |
| **E-3** | Непустые корни + `WINDOWS_RESTRICTED_TOKEN_SANDBOX` + токен | `SECURITY_BOUNDARY_VERIFIED` | `(True, 'SECURITY_BOUNDARY_VERIFIED: Isolated write boundary active...')` | **PASS** |

---

### 1.2. P0-B1: Выполненное действие инструмента против намерения (O-1 .. O-4)
- **Проблема**: Ранее диспетчер ориентировался на наличие `TOOL_CALL` или поля `tool_calls` в ответе планировщика, путая намерение агента вызвать инструмент с фактом его реального исполнения.
- **Исправление**:
  1. **O-1 (Tool Call без Tool Result)**: Если в транскрипте присутствует `TOOL_CALL`, но нет подтверждающего `TOOL_RESULT` (статус `DONE`/`SUCCESS`/`OK`), а агент выдаёт текст «Done», статус признаётся `TERMINAL_FAILURE` (`UNVERIFIED_OUTCOME: No successful tool execution occurred in session`).
  2. **O-2 (План без выполненных действий)**: `PLANNER_RESPONSE` с полем `tool_calls`, но без последующих событий исполнения инструмента, классифицируется как `DISPATCH_CONFIRMED` (`SESSION_AWAITING_ACTION_START`), но ни в коем случае не `RUNNING` и не `SUCCEEDED`.
  3. **O-3 (Предсуществующий файл)**: Наличие файла на диске до запуска сессии без подтверждённого события исполнения инструмента в транскрипте признаётся `TERMINAL_FAILURE` (`UNVERIFIED_OUTCOME`).
  4. **O-4 (Промежуточная ошибка и повтор в полёте)**: Промежуточный `TOOL_RESULT(status=ERROR)`, за которым следует повторный `TOOL_CALL`, признаётся состоянием `RUNNING` (`AGENT_EXECUTING_STEPS`). Диспетчер не завершает задачу преждевременно, не освобождает аренду worktree и не запускает вторую задачу.

#### Результаты нативного воспроизведения P0-B1:
| Сценарий | Транскрипт / Состояние | Ожидаемый статус | Фактический статус на Phase A | Вердикт |
|:---:|:---|:---:|:---:|:---:|
| **O-1** | `TOOL_CALL` без `TOOL_RESULT` + заявление «Done» | `TERMINAL_FAILURE` | `TERMINAL_FAILURE` (`UNVERIFIED_OUTCOME: No successful tool execution...`) | **PASS** |
| **O-2** | `PLANNER_RESPONSE(tool_calls=[...])` без шагов | `DISPATCH_CONFIRMED` | `DISPATCH_CONFIRMED` (`SESSION_AWAITING_ACTION_START...`) | **PASS** |
| **O-3** | Файл на диске создан до сессии, в сессии 0 шагов | `TERMINAL_FAILURE` | `TERMINAL_FAILURE` (`UNVERIFIED_OUTCOME: No successful tool execution...`) | **PASS** |
| **O-4** | `TOOL_RESULT(ERROR)` + in-flight retry `TOOL_CALL` | `RUNNING` | `RUNNING` (`AGENT_EXECUTING_STEPS: Correlated tool execution in progress...`) | **PASS** |

---

### 1.3. Интеграция с очередью: Обычная задача против контрактной TEST_ONLY
- **Обычная задача из inbox**: Не содержит контрактной схемы приёмки (`expected_artifacts = []`). По завершении сессии с выполненными инструментами диспетчер переводит её в `AWAITING_VERIFICATION` (а не в ложный `SUCCEEDED`) и помещает worktree в карантин (`WORKTREE_QUARANTINED`), блокируя запуск следующей задачи до проверки оператором.
- **Контрактная задача `TEST_ONLY`**: Содержит директиву `ACCEPTANCE_ARTIFACT: <path>`. Диспетчер проверяет выполнение инструментов в сессии, факт создания/обновления артефакта во время выполнения (проверка `mtime >= dispatched_at`), его ненулевой размер и соответствие хешу, после чего переводит задачу в `SUCCEEDED`.

---

## 2. Результаты расширенной матрицы проверок A4R-01 .. A4R-12

| Код | Приоритет | Наименование проверки | Ожидаемый результат | Фактический результат | Корпус вызовы | Вердикт |
|:---:|:---:|:---|:---|:---|:---:|:---:|
| **`A4R-01`** | P0 | Недоказанный профиль прав (дефолт, env=UNPROVEN, отсутствие boundary config) | `BLOCKED_SETUP_REQUIRED` во всех 4 случаях; строго 0 вызовов runner | `BLOCKED_SETUP_REQUIRED`, 0 вызовов runner; exit 126 на `_invoke_external_runner` | 0 | **PASS** |
| **`A4R-02`** | P0 | Проверенная граница безопасности (E-1..E-3) и запрет боевых корней | Разрешённый контур пропускает запуск; пустой список/нет аттестации/боевая база данных блокируют запуск | E-1..E-3 подтверждены: пустые корни -> BLOCKED; нет токена -> BLOCKED; боевой корень -> BLOCKED; валидный -> GO | 0 | **PASS** |
| **`A4R-03`** | P0 | Metadata-only и USER_INPUT-only в транскрипте | Статус строго `DISPATCH_CONFIRMED`; ни `RUNNING`, ни `SUCCEEDED` | `DISPATCH_CONFIRMED` во всех случаях, `outcome_verified=False` | 0 | **PASS** |
| **`A4R-04`** | P0 | «Начинаем?», SOFT_DENIED, отказ, O-1 tool call без result | `WAITING_CONFIRMATION` -> карантин; `SOFT_DENIED` / отказ / O-1 -> `TERMINAL_FAILURE` | Все сценарии отказа и O-1 подтверждены; worktree блокируется в карантине | 0 | **PASS** |
| **`A4R-05`** | P0 | Чужой хеш, префикс 12 символов, чужой rootId, O-2 intent-only | Безусловный возврат `UNKNOWN` на чужой хеш/rootId; O-2 -> `DISPATCH_CONFIRMED` | Чужие хеши отклонены (`UNKNOWN`); O-2 возвращает `DISPATCH_CONFIRMED` | 0 | **PASS** |
| **`A4R-06`** | P0 | Обычная задача (AWAITING_VERIFICATION) против контрактной TEST_ONLY | Обычная задача -> `AWAITING_VERIFICATION` + карантин; TEST_ONLY -> `SUCCEEDED` | Обычная задача блокирует очередь; контрактная валидирует артефакт и завершается | 0 | **PASS** |
| **`A4R-07`** | P0 | Обрыв хвоста JSONL и O-4 retry in-flight | R8 -> `UNKNOWN` (аренда не снята); O-4 -> `RUNNING` (аренда не снята, задача 2 блокирована) | R8 и O-4 подтверждены; аренда сохранена, второй запуск предотвращён | 0 | **PASS** |
| **`A4R-08`** | P0 | Таймаут/неопределённость лаунчера (2 задачи в очереди) | Первая задача -> `WORKTREE_QUARANTINED`; вторая задача НЕ запускается (0 вызовов) | Карантин сохранён, вызовы для задачи 2 = 0; карантин переживает перезапуск | 0 | **PASS** |
| **`A4R-09`** | P0 | Durable intent перед запуском и восстановление сбоя | Intent сохранён на диск до вызова runner; сбой mid-intent -> автокарантин при старте | `DISPATCHING_INTENT` зафиксирован на диске; сбой восстановлен как карантин (0 запусков) | 0 | **PASS** |
| **`A4R-10`** | P0 | Регрессионный пакет: CLI, tuple ordering, conflict, veto | CLI `--poll-once`/`--bootstrap` без ошибок; `(3, 10) > (3, 9)`; карантин конфликта; вето маркеров | Все регрессионные тесты пройдены без ошибок | 0 | **PASS** |
| **`A4R-11`** | P1 | Разделение контрактов и живого цикла безопасности | При наличии `watcher.pause` -> `PAUSED` (0 вызовов); при `UNVERIFIED` -> `BLOCKED` (0 вызовов) | Fail-closed подтверждён; контрактные моки не дают статус `LIVE_OBSERVED`; `LIVE_GATE: NOT_EXECUTED` | 0 | **PASS** |
| **`A4R-12`** | P1 | Согласованность отчёта и `effective_dispatch_state` | `get_status_report()` отражает паузу, карантин, границы; планировщик -> `CONFIGURED_UNOBSERVED` | Состояния согласованы; статус по питанию честно зафиксирован `CONFIGURED_UNOBSERVED` | 0 | **PASS** |

---

## 3. Сводка выполнения тестов (100 / 100 PASS)

- **`tests/test_autostart_dispatcher.py`**: **12 / 12 PASS** (2.157 с)  
  - 12 независимых целевых тестов матрицы A4R-01..A4R-12 без избыточных обёрток
- **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS** (1.249 с)  
- **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS** (13.593 с)  
  - Базовые контрактные тесты Stage 4.2.8: 40
  - Негативные тесты Revision 1 (NG-01..NG-10): 10
  - Негативные тесты Revision 2 (G2-01..G2-10): 10
  - Негативные тесты Revision 3 & 3.2 (G3-01..G3-10): 10
- **Итого**: **100 / 100 PASS (100%)**

---

## 4. Итоговые официальные статусы гейтов

- **`CONTRACT_GATE_READY`**: **`GO`** (70/70 контрактных тестов пройдены)
- **`AUTOSTART_CODE_GATE`**: **`GO`** (все замечания Rev 1.2 P0-E1 и P0-B1 устранены, fail-closed поведение и матрица A4R-01..A4R-12 подтверждены)
- **`AUTOSTART_READY`**: **`GO_PENDING_LIVE_CYCLE`** (ожидает подтверждённого прогона через Task Scheduler при наличии доказанного рантайм-контура)
- **`AUTOSTART_MODE`**: **`AUTO_EXECUTE_SCOPED`**
- **`LIVE_GATE`**: **`NOT_EXECUTED`** (на боевом Acer активен операторский `watcher.pause`)
- **`SESSION_RESTART_RECOVERY`**: **`CONFIGURED_UNOBSERVED`**
- **`WINDOWS_POWER_RECOVERY`**: **`CONFIGURED_UNOBSERVED`**
- **`REAL_CORPUS_PILOT`**: **`NOT_EXECUTED`** (`actual_search_calls = 0`)
- **`SNAPSHOT_READY`**: **`NO_GO`** (боевая БД в режиме READ-ONLY, WAL: 0 байт)
- **`MODEL_INDEX_IDENTITY`**: **`UNVERIFIED`**
- **`EMBEDDING_PROFILE`**: **`UNVERIFIED`**
- **`PRODUCTION_DEPLOYMENT`**: **`NOT_AUTHORIZED`** (боевой репозиторий на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`)
