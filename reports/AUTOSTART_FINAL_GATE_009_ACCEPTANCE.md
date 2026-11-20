# Stage 4.2.8 — AUTO-START-01 Provenance and Permissions Acceptance Report (TZ-009 Rev 1.0)

**Документ**: Отчёт о доказательной границе полномочий и достоверном результате исполнения AUTO-START-01 (ТЗ `FR-TZ-20261117-009` / Редакция 1.0 от 2026-11-17)  
**ТЗ**: `FR-TZ-20261117-009` / Stage 4.2.8 / AUTO-START-01 PROVENANCE AND PERMISSIONS / Редакция 1.0 от 2026-11-17  
**SHA-256 ТЗ**: `5d166b9a747941e22825b0745e72b767bf420a96f99f024871a93af3159a23d3` (19,999 байт)  
**Локальный путь ТЗ**: `<PATH_REDACTED>/Мой диск\FlyingRAG_TZ_Inbox\FR-TZ-20261117-009_AUTOSTART_PROVENANCE_AND_PERMISSIONS_3a63ed72_704ecf79.txt`  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: BLOCKED_SETUP_REQUIRED (GO_PENDING_LIVE_CYCLE) / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED**  
**Проверенный коммит кода (Phase A tested code anchor)**: [`a0dd1bc790df61259885e8c00af895cce3304659`](https://github.com/Kritik35/flying-rag-mcp/commit/a0dd1bc790df61259885e8c00af895cce3304659)  
**Tree SHA кода**: `1ce35b4ac5c93720064b8ff152000358a24091a3`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`704ecf79fcd91d82e763cd68ca21b8158a75a4a2`](https://github.com/Kritik35/flying-rag-mcp/commit/704ecf79fcd91d82e763cd68ca21b8158a75a4a2) (Tree: `f75c4e93abcf2ce11056628f4a8e59aef7a943fc`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`3a63ed72f5bdca2849d28edaa08e0894daa1d1b1`](https://github.com/Kritik35/flying-rag-mcp/commit/3a63ed72f5bdca2849d28edaa08e0894daa1d1b1) (Tree: `a4902418d62ae11b9c81f2b2c00f2c5cbf8652a0`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `<PRODUCTION_DB_METADATA>` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**  

---

## 1. Исправление замечаний независимой проверки ТЗ-009

Во исполнение адресных требований ТЗ `FR-TZ-20261117-009` устранены ложноположительные проверки границ прав и происхождения результатов выполнения:

### 1.1. P0-S1 & P0-S2: Устранение самодекларации аттестации и защита родительских каталогов
- **Проблема S1**: Метод `verify_security_boundary()` считал токен из локального JSON достаточным подтверждением, если он непустой. Внешняя валидация отсутствовала.
- **Проблема S2**: Проверка `p_root in a.parents` не отсекала случаи, когда `allowed_write_roots` включает родительский каталог (`<SYSTEM_DRIVE_ROOT>` или `<PRODUCTION_DIR>`), тем самым открывая доступ ко всей боевой структуре.
- **Исправление**:
  1. **Fail-Closed без самодекларации (P0-S1)**: Статический JSON с токеном больше не считается доказательством. Требуется подтверждение от активного внешнего провайдера/валидатора рантайм-изоляции (`runtime_isolation_validator`). Без него диспетчер честно возвращает `BLOCKED_SETUP_REQUIRED` и выполняет **строго 0 вызовов runner**.
  2. **Двунаправленная проверка запрещённых путей (P0-S2)**: Проверяются:
     - Равенство пути: `a == p_root`;
     - `a in p_root.parents`: разрешённый путь является предком/родителем боевого корня (`<SYSTEM_DRIVE_ROOT>`, `<PRODUCTION_DIR>`);
     - `p_root in a.parents`: боевой корень является предком разрешённого пути.
     Любое пересечение немедленно блокирует запуск с `BLOCKED_SETUP_REQUIRED`.
  3. **Защита системных корней и дисков**: Запрещены целые диски (`<SYSTEM_DRIVE_ROOT>`), UNC-пути (`<UNC_SHARE>`), пути с обходом каталогов (`..`) и системные папки Windows (`<SYSTEM_DIR>`, `<SYSTEM_PROGRAMS_DIR>`).
  4. **Состояние на боевом Acer**: Поскольку пользователь `almax` работает в стандартной среде Windows без контейнера изоляции, диспетчер штатно возвращает `BLOCKED_SETUP_REQUIRED`, предотвращая несанкционированные действия.

---

### 1.2. P0-O1 & P0-O2: Контрактная верификация артефактов и причинно-следственная связь инструментов
- **Проблема O1**: `ACCEPTANCE_ARTIFACT` извлекался как произвольная строка; для неё проверялись только `exists()` и размер > 0 без проверки времени изменения, безопасного корня и хеша.
- **Проблема O2**: Код считал любой успешный `TOOL_RESULT` (например, от `read_file`) достаточным для признания успеха сессии, даже если требуемый артефакт существовал заранее и не создавался агентом.
- **Исправление**:
  1. **Канонизация и изоляция путей артефактов (P0-O1)**: `ACCEPTANCE_ARTIFACT` извлекается только для задач с заголовком `TASK_TYPE: TEST_ONLY`. Пути с обходом (`..`) или ведущие за пределы доверенного тестового каталога (`worktree`, `state_dir`, `temp`) немедленно отклоняются.
  2. **Проверка свежести артефакта (S3-05)**: Фиксируется точное время отправки задачи (`dispatched_at`). Время модификации файла `mtime` обязано быть строго после момента отправки. Предсуществующие файлы безусловно возвращают `TERMINAL_FAILURE` (`STALE_PREEXISTING_ARTIFACT`).
  3. **Причинно-следственная связь инструментов (P0-O2 / S3-06)**: Для задач с артефактами проверяется, что сессия выполнила именно файл-модифицирующий инструмент (`write_file`, `edit_file`, `run_command`), таргетирующий требуемый файл, и получила успешный `TOOL_RESULT`. Запуск немодифицирующих инструментов (`read_file`) при наличии файла на диске возвращает `TERMINAL_FAILURE` (`UNVERIFIED_OUTCOME: Required artifact was not produced by an executed write action in session`).
  4. **Целостность вызовов инструментов (S3-07)**: Проверяется соответствие `call_id` между `TOOL_CALL` и `TOOL_RESULT`. Осиротевшие или поддельные результаты инструментов без соответствующего вызова возвращают `UNKNOWN`.
  5. **Обычные задачи**: Задачи без контрактной схемы `TEST_ONLY` завершаются статусом `AWAITING_VERIFICATION` и помещаются в карантин (`WORKTREE_QUARANTINED`), исключая ложный `SUCCEEDED`.

---

## 2. Результаты нативного воспроизведения проверок S3-01 .. S3-08

```
Starting native module replay for TZ-009 (S3-01..S3-08)...
PASS: S3-01 -> (False, 'BLOCKED_SETUP_REQUIRED: Runtime isolation cannot be proven from static local con...')
PASS: S3-02 -> (False, 'BLOCKED_SETUP_REQUIRED: Runtime isolation attestation rejected: TOKEN_EXPIRED_OR...')
PASS: S3-03 -> (False, 'BLOCKED_SETUP_REQUIRED: Prohibited root <PRODUCTION_DB_METADATA> an...')
PASS: S3-04 -> Unobserved: (False, 'BLOCKED_SETUP_REQUIRED: Runtime isolation attestation reject...'), Verified: (True, 'SECURITY_BOUNDARY_VERIFIED: Runtime isolation verified by pr...')
PASS: S3-05 -> (TERMINAL_FAILURE, 'STALE_PREEXISTING_ARTIFACT: Artifact stale_artifact.txt was not modified after t...')
PASS: S3-06 -> (TERMINAL_FAILURE, 'UNVERIFIED_OUTCOME: Required artifact read_only_artifact.txt was not produced by...')
PASS: S3-07 -> (UNKNOWN, 'ORPHANED_TOOL_RESULT: TOOL_RESULT call_id 'call-forged-999' has no matching TOOL...')
PASS: S3-08 -> (TERMINAL_SUCCESS, 'SESSION_TERMINAL_VERIFIED: Correlated terminal outcome, verified causality, and ...')
All TZ-009 native module replays (S3-01..S3-08) PASSED successfully!
```

---

## 3. Сводка выполнения тестов (109 / 109 PASS)

- **`tests/test_autostart_provenance_and_permissions.py`**: **9 / 9 PASS** (0.957 с)  
  - Целевой проверочный пакет проверок S3-01 .. S3-10
- **`tests/test_autostart_dispatcher.py`**: **12 / 12 PASS** (1.706 с)  
  - Регрессионная матрица A4R-01 .. A4R-12 (включая R1–R8 и O-1..O-4)
- **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS** (1.250 с)  
- **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS** (13.500 с)  
  - Базовые контрактные тесты Stage 4.2.8: 40
  - Негативные тесты Revision 1 (NG-01..NG-10): 10
  - Негативные тесты Revision 2 (G2-01..G2-10): 10
  - Негативные тесты Revision 3 & 3.2 (G3-01..G3-10): 10
- **Итого**: **109 / 109 PASS (100%)**

---

## 4. Итоговые официальные статусы гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`CONTRACT_GATE_READY`** | **`GO`** | 70/70 контрактных тестов пройдены. |
| **`AUTOSTART_CODE_GATE`** | **`GO`** | Устранены замечания ТЗ-009 (P0-S1, P0-S2, P0-O1, P0-O2), 109/109 тестов пройдены. |
| **`AUTOSTART_READY`** | **`BLOCKED_SETUP_REQUIRED`** | На реальном хосте Acer отсутствует ОС-контейнер/песочница; fail-closed защита честно блокирует запуск до настройки оператором. |
| **`AUTOSTART_MODE`** | **`AUTO_EXECUTE_SCOPED`** | Активирован в конфигурации; исполнение блокируется политикой безопасности и паузой. |
| **`LIVE_GATE`** | **`NOT_EXECUTED`** | На боевом Acer активен операторский стоп-маркер `watcher.pause`. |
| **`SESSION_RESTART_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Схема v2 и durable intent настроены в коде; реальный сбой daemon не симулировался. |
| **`WINDOWS_POWER_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | `StartWhenAvailable = true` включён в Task Scheduler; физический цикл сна не наблюдался. |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированная копия БД не создавалась. База `metadata.db` в режиме READ-ONLY (WAL: 0 байт). |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Сервер 8089 выключен. Проверка размерности модели не выполнялась. |
| **`EMBEDDING_PROFILE`** | **`UNVERIFIED`** | Профиль совместимости модели с LanceDB не подтверждён живым прогоном. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | Вызовов к боевому корпусу строго 0 (`actual_search_calls = 0`). |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 5. Требуемое действие оператора

Для перехода от статуса `BLOCKED_SETUP_REQUIRED` к боевому автозапуску требуется однократное действие:
- Настроить изолированный профиль исполнения для агента (AppContainer, Windows Sandbox или Docker/WSL2 контейнер с принудительным ограничением монтирования только каталогов `worktree` и `temp`).
- При отсутствии такой настройки автоматический диспетчер остаётся в безопасном состоянии `BLOCKED_SETUP_REQUIRED` (0 несанкционированных вызовов к production).
