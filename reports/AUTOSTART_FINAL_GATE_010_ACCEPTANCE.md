# Stage 4.2.8 — AUTO-START-01 Final Acceptance Report (TZ-010)

**Документ**: Отчёт о финальной адресной коррекции доказательств выполнения и безопасных границ (ТЗ `FR-TZ-20261117-010` / Редакция 1.0 от 2026-11-17)  
**ТЗ**: `FR-TZ-20261117-010` / Stage 4.2.8 / AUTO-START-01 / Финальная адресная коррекция доказательств выполнения и безопасных границ (LIMITED CODE CLOSURE)  
**SHA-256 ТЗ**: `25d8c4b11dd13e5264ad65fdf80b7ea289dce85890b7582b47dbdcb524a7be47` (19,467 байт)  
**Локальный путь ТЗ**: [FR-TZ-20261117-010_AUTOSTART_EVIDENCE_CLOSURE_a0dd1bc790df61259885e8c00af895cce3304659.txt](file:///G:/Мой%20диск/FlyingRAG_TZ_Inbox/FR-TZ-20261117-010_AUTOSTART_EVIDENCE_CLOSURE_a0dd1bc790df61259885e8c00af895cce3304659.txt)  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: BLOCKED_SETUP_REQUIRED (GO_PENDING_LIVE_CYCLE) / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED**  

---

## 1. Проверенная цепочка коммитов (Git Provenance)

- **Репозиторий**: `https://github.com/Kritik35/flying-rag-mcp`
- **Целевая ветка**: `audit/stage4-2-verification`
- **Проверенный коммит кода (Phase A tested code anchor)**: [`dcf98d5039808b01462b420993feba48ac600cfe`](https://github.com/Kritik35/flying-rag-mcp/commit/dcf98d5039808b01462b420993feba48ac600cfe)
  - **Tree SHA кода**: `dc7ca2772f80e033bac20d1485bb26faf2eb09ed`
  - **Parent SHA**: `12f15b5be3eb67ad43c93b36c3b542b5cd8b5346`
  - **Начальный коммит Phase A**: [`12f15b5be3eb67ad43c93b36c3b542b5cd8b5346`](https://github.com/Kritik35/flying-rag-mcp/commit/12f15b5be3eb67ad43c93b36c3b542b5cd8b5346) (Tree: `f88533399e201754ab40eb063af8b4688ba1415e`, Parent: `c5cf3aef6ad436b348a01b46152f2d2b65c217cd`)
- **Предыдущий отчётный коммит (preceding reports HEAD)**: [`c5cf3aef6ad436b348a01b46152f2d2b65c217cd`](https://github.com/Kritik35/flying-rag-mcp/commit/c5cf3aef6ad436b348a01b46152f2d2b65c217cd) (Tree: `33d185e4ddc3a538a19b9adb5343060c483463ff`)
- **Предыдущий коммит кода (prior tested code anchor)**: [`a0dd1bc790df61259885e8c00af895cce3304659`](https://github.com/Kritik35/flying-rag-mcp/commit/a0dd1bc790df61259885e8c00af895cce3304659) (Tree: `1ce35b4ac5c93720064b8ff152000358a24091a3`)
- **Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)
- **Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)
- **Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)
- **Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**

---

## 2. Реализация требований ТЗ-010 (C4-01 .. C4-10)

### 2.1. P0-O3: Обязательное сопоставление по call_id и запрет позиционной привязки (C4-01 .. C4-03)
1. **C4-01 [P0]**: События `TOOL_CALL` и `TOOL_RESULT` без `call_id` не позволяют установить достоверную причинную связь. Сессия с такими событиями переводится в `AWAITING_VERIFICATION` (а не в ложный `SUCCEEDED`).
2. **C4-02 [P0]**: Позиционное сопоставление (`elif idx < len(...)`) полностью удалено из кода. При наличии нескольких вызовов разных инструментов и одиночного `DONE` без `call_id` привязка результата к модифицирующему инструменту запрещена -> `AWAITING_VERIFICATION`.
3. **C4-03 [P0]**: Сиротский или чужой результат инструмента (`TOOL_RESULT` с неизвестным `call_id` или `call_id` другой сессии) возвращает `UNKNOWN` (`ORPHANED_TOOL_RESULT`). Worktree блокируется, 0 освобождений аренды.

### 2.2. P0-O4: Строгая причинность инструментов записи (C4-04)
1. **Запрет подтверждения через run_command**: Команда `run_command` (например, `echo filename`, `cat filename`, grep) больше не признаётся модифицирующим инструментом для контрактных задач; без доказанной аттестации записи возвращается `TERMINAL_FAILURE` (`UNVERIFIED_OUTCOME`).
2. **Запрет сопоставления по substring/пустому пути**: Совпадение имени файла (`art_p.name in target_path`) или пустой путь `Path: ""` запрещены. Требуется строгое совпадение канонического нормализованного пути (`target_p == art_p`) исключительно для инструментов `write_file` и `edit_file`.

### 2.3. P0-O5: Доверенный контракт артефактов и атомарность отметки времени (C4-05 .. C4-06)
1. **C4-05 [P0]**: Для контрактных задач `TASK_TYPE: TEST_ONLY` директива `ACCEPTANCE_ARTIFACT_SHA256` является обязательной. Задачи без хеша, с путями `..` или путями непосредственно в корне `state_dir` либо корне системного temp бракуются (`is_safe = False`, `TERMINAL_FAILURE`).
2. **C4-06 [P0]**: Отметка времени намерения диспетчеризации (`dispatch_intent_ts`) и снимок предсуществующего состояния артефакта фиксируются **до** вызова внешнего исполнителя runner. Создание артефакта во время выполнения runner признаётся свежим. Предсуществующий файл, изменённый до диспетчеризации, надёжно обнаруживается и бракуется (`STALE_PREEXISTING_ARTIFACT`).

### 2.4. P0-S4: Локальное вето области разрешённой записи (C4-07)
1. **C4-07 [P0]**: Введён локальный фильтр `verify_security_boundary()`: все пути в `allowed_write_roots` обязаны являться подмножеством доверенных изолированных областей (`worktree_dir`, `state_dir`, `temp`). Пути вне доверенного контура (например, `D:\other_data`) блокируются локальным вето (`BLOCKED_SETUP_REQUIRED`) с 0 запусков runner, даже если внешняя фиктивная функция валидатора вернула `True`.

### 2.5. C4-08: Позитивная контрактная ветка CONTRACT_ONLY
1. **C4-08 [P0]**: При наличии явного изолированного тестового каталога, совпадения `call_id` для инструмента `write_file`, точного нормализованного пути и совпадения SHA-256 регистрируется `TERMINAL_SUCCESS` -> `SUCCEEDED`.
2. **Явное указание**: Данный артефакт создаётся тестовым harness; это доказывает корректность логики диспетчера, но **НЕ является живым доказательством автономной работы агента без песочницы** (`CONTRACT_ONLY`).

### 2.6. C4-09 .. C4-10: Сохранение матрицы тестов и честные статусы гейтов
1. **C4-09 [P1]**: Сохранены без регрессий все 9 проверок S3, 12 проверок A4R, 18 проверок watcher и 70 проверок shadow pilot.
   - **Явный маппинг S3-09**: `NOT_SEPARATE_CASE` (субсумирован в S3-08 / C4-08 как интеграция подтверждённого терминального успеха).
2. **C4-10 [P1]**: При активном `watcher.pause` или отсутствии реального контейнера изоляции Windows:
   - `LIVE_GATE = NOT_EXECUTED`
   - `AUTOSTART_READY = BLOCKED_SETUP_REQUIRED`
   - `AUTOSTART_CODE_GATE = GO`
   - Ложный `FINAL_GO` исключён.

---

## 3. Результаты нативного воспроизведения C4-01 .. C4-08

```
=== NATIVE REPLAY C4-01 .. C4-08 ===
C4-01: (AWAITING_VERIFICATION, 'UNVERIFIED_TOOL_CORRELATION: Tool events lack unique matching call_id pairs (C4-01/C4-02)')
C4-02: (AWAITING_VERIFICATION, 'UNVERIFIED_TOOL_CORRELATION: Tool events lack unique matching call_id pairs (C4-01/C4-02)')
C4-03: (UNKNOWN, 'ORPHANED_TOOL_RESULT: TOOL_RESULT call_id 'call-foreign-999' has no matching TOOL_CALL (S3-07/C4-03)')
C4-04: (TERMINAL_FAILURE, 'UNVERIFIED_OUTCOME: Required artifact art_01.txt was not produced by an executed write action in session. Only non-modifying tools executed or run_command without write attestation (C4-04)')
C4-05: is_safe=False, error='MISSING_MANDATORY_ARTIFACT_SHA256 (C4-05)'
C4-06: (TERMINAL_FAILURE, 'STALE_PREEXISTING_ARTIFACT: Artifact stale.txt was not modified after task dispatch (mtime ... < dispatch ...) (C4-06)')
C4-07: (False, 'BLOCKED_SETUP_REQUIRED: Allowed write root D:\other_data is outside trusted isolated workspace scope (must be within worktree, state_dir, or temp) (P0-S4 / C4-07)')
C4-08: (TERMINAL_SUCCESS, 'SESSION_TERMINAL_VERIFIED: Correlated terminal outcome, verified causality, and fresh artifacts (C4-08)')
```

---

## 4. Сводка выполнения тестов (119 / 119 PASS — 100%)

Все 119 тестов выполнены на хосте Acer за 13.48 с с использованием окружения `C:\RAG_Acer\venv\Scripts\python.exe`:
1. **`tests/test_autostart_evidence_closure.py`**: **10 / 10 PASS** (1.078 с)
   - C4-01 .. C4-10: закрытие всех дефектов сопоставления, причинности, вето и отчётности
2. **`tests/test_autostart_provenance_and_permissions.py`**: **9 / 9 PASS** (0.950 с)
   - S3-01 .. S3-10: доказательная граница прав и защита от старых файлов (S3-09 субсумирован в S3-08)
3. **`tests/test_autostart_dispatcher.py`**: **12 / 12 PASS** (2.120 с)
   - A4R-01 .. A4R-12: интеграционная матрица диспетчера и обработка очередей
4. **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS** (1.205 с)
   - Базовые сценарии монитора Google Drive
5. **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS** (8.129 с)
   - 40 базовых контрактных + 10 NG + 10 G2 + 10 G3
- **Итого**: **119 / 119 PASS (100%)**

---

## 5. Итоговые официальные статусы гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`CONTRACT_GATE_READY`** | **`GO`** | 70/70 контрактных тестов пройдены. |
| **`AUTOSTART_CODE_GATE`** | **`GO`** | Устранены все 4 дефекта ТЗ-010: введён строгий запрет позиционной привязки, исключён `run_command` для доказательства записи, внедрена преддиспетчерская фиксация свежести артефактов и локальное вето корней записи (119/119 тестов пройдены). |
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
