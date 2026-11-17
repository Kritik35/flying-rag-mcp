# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — PILOT-ENTRY-01 + WATCHER-BOOT-RECOVERY-01 (ТЗ `FR-TZ-20261117-011` / Редакция 1.0 от 17.11.2026, SHA-256 `02b72d800058645dd30c8e65eb8048ef1ec7b1ab118feed056b182792dd63a80`, 23 762 байта)  
**Статус документа**: **`PILOT_READY_FOR_APPROVAL: GO` / `BOOT_RECOVERY: CONFIGURED_UNOBSERVED` / `DETECTION_DELIVERY: OPERATIONAL` / `SNAPSHOT_READY: NO_GO` / `REAL_CORPUS_PILOT: NOT_EXECUTED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенный коммит кода (tested code anchor)**: [`9b95161eaf8bfe7b512babc9dacc8d3c19cbc5d4`](https://github.com/Kritik35/flying-rag-mcp/commit/9b95161eaf8bfe7b512babc9dacc8d3c19cbc5d4) (Tree: `dce08a118d1ca1dac28c1082b3de9531bc5b2f20`)  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`52c58067dfc2e451e8d3249206af876f25d3e85d`](https://github.com/Kritik35/flying-rag-mcp/commit/52c58067dfc2e451e8d3249206af876f25d3e85d) (Tree: `d6144d85e698edca896503b714fbbdc80358fadf`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH  

---

## 1. Итоги выполнения ТЗ-011

### 1.1. P0 — Восстановление автоматического мониторинга Google Drive
- **Windows Task Scheduler**: Задача `\FlyingRAG_Drive_Inbox_Watcher` обновлена: добавлен триггер входа пользователя `<LogonTrigger>` (задержка 30 секунд для монтирования диска `G:`) с сохранением периодического запуска каждые 5 минут (`<TimeTrigger>`).
- **Резервная копия**: Сохранена в [task_backup.xml](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/05_drive_watcher/task_backup.xml).
- **Разграничение подсистем**:
  - `Detection / Delivery`: Активна и работает в фоне. ТЗ-011 автоматически обнаружено и поставлено в очередь (`job_FR-TZ-20261117-011_rev1_0_02b72d800058`).
  - `Dispatch / Execution`: Заблокирована операторским маркером `watcher.pause` (`PAUSED_BY_OPERATOR`).
- **Идемпотентность**: Повторный опрос проверен (0 дубликатов, 0 новых задач, 0 запусков агентов).
- **Статус восстановления**: **`BOOT_RECOVERY: CONFIGURED_UNOBSERVED`** (ожидает подтверждения после первой естественной перезагрузки оператором).

### 1.2. P1 — Подготовка поискового пилота (Pilot Entry)
- **Инвентарь хранилищ**:
  - SQLite `metadata.db`: 1.485 GB, WAL: 0 байт.
  - LanceDB: 203 файла, 5.339 GB.
  - Таблицы Parquet: 2 469 файлов, 54.97 MB.
  - Свободно на диске C:: **60.71 GiB (65.19 GB)** (запас >9.5x).
  - Активные пишущие процессы: **0**.
- **План независимого изолированного снимка**: Разработан регламент копирования в `C:\Acer_System_Audit\rag_quality_ab_20261113\isolated_pilot_data` с собственной конфигурацией кэша и логов, без hardlinks/symlinks, с проверкой целостности через `PRAGMA integrity_check`. Сам снимок до согласования **не создавался**.
- **3-Query Smoke Protocol**: Отобраны 3 запроса из канонического манифеста `pilot_query_manifest_105.json`:
  1. `Q004`: `СП 7.13130 пункт 6.4` (конкретный пункт СП/ГОСТ: пределы огнестойкости воздуховодов).
  2. `Q010`: `СП 7.13130 пункт 6.10` (числовая инженерная норма: пределы огнестойкости клапанов EI 60, EI 90, EI 15).
  3. `Q088`: `СП 60.13330 пункт 7.1.1` (неоднозначные редакции: разрешение коллизии СП 60 2012 vs 2020).
- **Сервер эмбеддингов**: Запущен на `127.0.0.1:8089` (`HEALTHY`, Dim=1024). Зафиксировано, что совпадение размерности не является криптографическим доказательством идентичности модели весам индекса (`MODEL_INDEX_IDENTITY=UNVERIFIED`).

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`PILOT_READY_FOR_APPROVAL`** | **`GO`** | Подготовлен воспроизводимый протокол 3-query smoke test и план изолированного снимка. |
| **`BOOT_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Задача в Task Scheduler настроена на вход пользователя и 5-минутный интервал; ожидает наблюдения после следующего ребута. |
| **`DETECTION_DELIVERY`** | **`OPERATIONAL`** | Монитор работает по расписанию, ТЗ-011 успешно обнаружено и поставлено в очередь. |
| **`CONTRACT_GATE_READY`** | **`GO`** | 70/70 контрактных тестов пройдены. |
| **`AUTOSTART_CODE_GATE`** | **`GO`** | Принято в ТЗ-010 Rev 1.1 (коммит `9b95161`). |
| **`AUTOSTART_READY`** | **`BLOCKED_SETUP_REQUIRED`** | Внешняя ОС-изоляция (AppContainer/Docker) не настроена. Диспетчер блокирует автозапуск. |
| **`AUTOSTART_MODE`** | **`AUTO_EXECUTE_SCOPED`** | Активирован с вето на запись. |
| **`LIVE_GATE`** | **`NOT_EXECUTED`** | На станции Acer действует операторский стоп-маркер `watcher.pause`. |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированная копия боевой базы данных не создавалась до подтверждения оператором. |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Сервер эмбеддингов запущен, но косинусный замер совместимости с индексом не проводился. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | К боевому корпусу выполнено ровно 0 поисковых вызовов (`actual_search_calls = 0`). |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остаётся строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 3. Детальные отчёты этапа

- [WATCHER_BOOT_RECOVERY_011.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/WATCHER_BOOT_RECOVERY_011.md) / [watcher_boot_recovery_011.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/watcher_boot_recovery_011.json) — Восстановление монитора Drive после ребута.
- [PILOT_ENTRY_011.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_ENTRY_011.md) / [pilot_entry_011.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_entry_011.json) — Подготовка поискового пилота и форма допуска A/B/C.
