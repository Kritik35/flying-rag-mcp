# Отчёт по задаче P0: WATCHER-BOOT-RECOVERY-01 (ТЗ-011)

**Документ**: Отчёт о восстановлении автоматического мониторинга Google Drive после перезагрузки и интерактивного входа в Windows (ТЗ `FR-TZ-20261117-011`, Редакция 1.0 от 17.11.2026)  
**ТЗ**: `FR-TZ-20261117-011` / `PILOT-ENTRY-01 + WATCHER-BOOT-RECOVERY-01`  
**SHA-256 ТЗ**: `02b72d800058645dd30c8e65eb8048ef1ec7b1ab118feed056b182792dd63a80` (23 762 байта)  
**Локальный путь ТЗ**: [FR-TZ-20261117-011_PILOT_ENTRY_BOOT_WATCHER_52c58067_FlyingRAG.txt](file:///G:/Мой%20диск/FlyingRAG_TZ_Inbox/FR-TZ-20261117-011_PILOT_ENTRY_BOOT_WATCHER_52c58067_FlyingRAG.txt)  
**Дата выполнения**: 17 ноября 2026 года  
**Статус восстановления**: **`BOOT_RECOVERY: CONFIGURED_UNOBSERVED` (готовность подтверждена конфигурацией и тестовым прогоном; ожидает первого наблюдения после физической перезагрузки оператором)**  

---

## 1. Разделение подсистем Detection и Dispatch

В соответствии с требованиями ТЗ-011 зафиксировано строгое разграничение двух независимых подсистем:
1. **Подсистема обнаружения и доставки (Detection / Delivery)**:
   - **Механизм**: Windows Task Scheduler -> `drive_inbox_watcher.py --poll-once` -> доступ к диску `G:\Мой диск\FlyingRAG_TZ_Inbox` -> обновление `state.json` / `inbox_spool` / `execution_queue`.
   - **Статус**: **ПОЛНОСТЬЮ АКТИВНА И ВОССТАНОВЛЕНА**. Задача запускается автоматически каждые 5 минут и при интерактивном входе пользователя.
2. **Подсистема диспетчеризации и исполнения (Dispatch / Execution)**:
   - **Механизм**: запуск сессий Gemini и агентов.
   - **Статус**: **ЗАБЛОКИРОВАНА РЕГЛАМЕНТОМ** (`PAUSED_BY_OPERATOR` / `BLOCKED_SETUP_REQUIRED`). Маркер `watcher.pause` сохранён и защищён от несанкционированного снятия. Факт обнаружения файла не означает и не подменяет успешное исполнение.

---

## 2. Инвентарь и обновление Windows Task Scheduler

### 2.1. Исходное состояние задачи (До изменений)
- **Имя задачи**: `\FlyingRAG_Drive_Inbox_Watcher`
- **Триггеры**: Только один `<TimeTrigger>` (повторение каждые 5 минут, начиная с 16.11.2026 09:00:00). Триггер входа в систему (`LogonTrigger`) отсутствовал.
- **Принципал**: `DESKTOP-18PI3UG\almax` (`InteractiveToken`).
- **Политика**: `StartWhenAvailable: true`, `MultipleInstancesPolicy: IgnoreNew`.
- **Резервная копия**: Сохранена в [task_backup.xml](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/05_drive_watcher/task_backup.xml).

### 2.2. Применённое обновление конфигурации (После изменений)
В задачу добавлен триггер входа пользователя с задержкой 30 секунд для гарантированного монтирования виртуального диска Google Drive `G:`.
- **XML-манифест**: Сохранён в [task_updated.xml](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/05_drive_watcher/task_updated.xml).
- **Обновлённые триггеры**:
  1. `<LogonTrigger>`: `Enabled: true`, `Delay: PT30S` — срабатывает через 30 секунд после интерактивного входа пользователя `almax`.
  2. `<TimeTrigger>`: `StartBoundary: 2026-11-16T09:00:00`, `Repetition: Interval PT5M` — обеспечивает периодический опрос каждые 5 минут.
- **Сохранённые параметры безопасности**:
  - `LogonType`: `InteractiveToken` (запуск строго в сеансе пользователя, без сохранения паролей и без привилегий SYSTEM).
  - `DisallowStartIfOnBatteries`: `true`, `StopIfGoingOnBatteries`: `true` (защита электропитания ноутбука сохранена).
  - `MultipleInstancesPolicy`: `IgnoreNew` (гарантирует отсутствие параллельных процессов).
  - `Command`: `C:\RAG_Acer\venv\Scripts\python.exe`.
  - `Arguments`: `C:\Acer_System_Audit\rag_quality_ab_20261113\worktree_stage3\scripts\drive_inbox_watcher.py --poll-once`.

---

## 3. Верификация работы мониторинга и идемпотентности

1. **Обнаружение ТЗ-011**:
   - Задача запущена штатно через Task Scheduler в 23:12:35 (код возврата `0`).
   - Файл `FR-TZ-20261117-011_PILOT_ENTRY_BOOT_WATCHER_52c58067_FlyingRAG.txt` успешно обнаружен и занесён в очередь:
     - `job_id`: `job_FR-TZ-20261117-011_rev1_0_02b72d800058`
     - `task_id`: `FR-TZ-20261117-011`
     - `revision`: `1.0`
     - `status`: `QUEUED`
     - `sha256`: `02b72d800058645dd30c8e65eb8048ef1ec7b1ab118feed056b182792dd63a80`
   - Диспетчер проверил наличие `watcher.pause`: автозапуск отклонён (`status: PAUSED`, `dispatched_count: 0`).
2. **Проверка идемпотентности (Второй цикл опроса без новых файлов)**:
   - `detected_count: 0`
   - `enqueued_count: 0`
   - `new_events: []`
   - `dispatched_count: 0`
   - Очередь сохранена в неизменном виде (22 задачи), дубликатов нет.
3. **Обработка временной недоступности диска G:**:
   - В коде `drive_inbox_watcher.py` (строки 764–768, 2023–2024) при отсутствии диска `G:` фиксируется статус `INBOX_UNAVAILABLE` / `INBOX_NOT_FOUND` без сброса очереди и без аварийного завершения. Очередной опрос возобновляется автоматически при появлении тома.

---

## 4. Инструкция для оператора: Проверка после перезагрузки Acer

> [!IMPORTANT]
> Самостоятельная перезагрузка рабочей станции Acer агентом Gemini запрещена регламентом.  
> После следующей штатной перезагрузки ноутбука и входа в Windows пользователю `almax` рекомендуется выполнить следующие команды проверки.

### Шаг 1. Проверка доступности виртуального тома Google Drive
```powershell
Test-Path "G:\Мой диск\FlyingRAG_TZ_Inbox"
```
*Ожидаемый результат*: `True`.

### Шаг 2. Проверка состояния задачи в планировщике Windows
```powershell
schtasks /query /tn FlyingRAG_Drive_Inbox_Watcher /v /fo list
```
*Ожидаемые поля*:
- `Status: Ready`
- `Last Result: 0`
- `Next Run Time`: время ближайшего 5-минутного интервала.

### Шаг 3. Проверка актуальности метки последнего опроса и очереди
```powershell
Get-Content C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\state.json | ConvertFrom-Json | Select-Object last_poll_utc, watcher_mode, @{N='queue_items';E={$_.execution_queue.PSObject.Properties.Count}}
```
*Ожидаемые поля*:
- `last_poll_utc`: свежая отметка времени после входа в систему (с разницей не более 5 минут от текущего времени).
- `watcher_mode`: `AUTO_EXECUTE_SCOPED`.
- `queue_items`: 22 (или более при появлении новых файлов).

---

## 5. Статусы готовности

- **`DETECTION_DELIVERY`**: **`OPERATIONAL`** (проверено штатным планировщиком и тестовым поллом).
- **`BOOT_RECOVERY`**: **`CONFIGURED_UNOBSERVED`** (настроено в XML, ожидает естественного цикла перезагрузки).
- **`WATCHER_PAUSE`**: **`ACTIVE`** (`watcher.pause` не удалялся).
- **`AUTOSTART_READY`**: **`BLOCKED_SETUP_REQUIRED`**.
