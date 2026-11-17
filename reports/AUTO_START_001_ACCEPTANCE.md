# Stage 4.2.8 — AUTO-START-01: Autonomous Task Ingestion & Execution Acceptance Report

**Документ**: Отчёт о приёмке механизма автономного запуска и исполнения заданий AUTO-START-01  
**ТЗ**: `FR-TZ-20261117-006` / PILOT-GATE-01 Revision 3 + AUTO-START-01 (`1cbd6411e21298d9ec8594f77e3c03fe6eff7be80418799423a378de5e0e86c1`, Редакция 3.1 от 2026-11-17)  
**Google Drive ID**: `1SZ2oPnmydcxFQFEzF4F8jzjvLO_K5OtR`  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **AUTOSTART_READY: GO / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED**  
**Проверенный коммит кода (tested code anchor)**: [`238ae2668aa1985996c439d4bffc428572a18a44`](https://github.com/Kritik35/flying-rag-mcp/commit/238ae2668aa1985996c439d4bffc428572a18a44)  
**Tree SHA кода**: `6f78e3da04700a02c9f993d8a8c9363f8fb42b51`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`dd54dfcda15a5ea39a93513286490d8bc9487588`](https://github.com/Kritik35/flying-rag-mcp/commit/dd54dfcda15a5ea39a93513286490d8bc9487588) (Tree: `1c96829784b0a2ca218d2e6c325f014dd173b387`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, не изменялась)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**  

---

## 1. Назначение и основания дополнения AUTO-START-01

Во исполнение прямого поручения оператора от 17 ноября 2026 года устранено принципиальное ограничение прежней архитектуры: **«обнаружение не равно выполнению»**.

В предыдущих редакциях `scripts/drive_inbox_watcher.py` функционировал строго в режиме `DETECTION_ONLY` (завершая цепочку статусом `ACKNOWLEDGED` и требованием ручного подтверждения оператором). Это приводило к тому, что при появлении нового валидного ТЗ в Google Drive исполнитель останавливался с вопросом «Начинаем?», требуя дополнительного диалогового подтверждения.

В рамках дополнения AUTO-START-01 реализован и аттестован полноценный контур автономного запуска:
1. **Подключение реального интерфейса исполнения (P0-D1)**: подключён штатный CLI/RPC интерфейс `C:\Users\almax\.gemini\antigravity\bin\agentapi.bat`, запускающий сессии `language_server.exe agentapi new-conversation`.
2. **Очередь, статусы и защита от повторного выполнения (P0-D2)**: схема состояния расширена до версии 2 с разделением `delivery_status` (`ACKNOWLEDGED`) и `execution_status` (`QUEUED -> DISPATCHING -> RUNNING -> SUCCEEDED / FAILED / BLOCKED / PAUSED / SUPERSEDED / DISPATCH_UNKNOWN`). Введён кросс-процессный мьютекс `execution.lock` с лизингом на 300 секунд, гарантирующий не более 1 активного агента-исполнителя.
3. **Безопасная миграция и управление редакциями (P0-D3)**: автоматическая миграция состояния с созданием резервной копии `state.json.bak_migration_<ts>`, сохранением исторической завершённости старых этапов и корректным замещением версий (`SUPERSEDED`).
4. **Планировщик, доступность и управляемая остановка (P1)**: служба Windows Task Scheduler `FlyingRAG_Drive_Inbox_Watcher` обновлена с параметрами `StartWhenAvailable=true`, `MultipleInstancesPolicy=IgnoreNew`, `InteractiveToken`, с сохранением интервала опроса 5 минут (`PT5M`). Введён операторский флаг паузы `watcher.pause`.
5. **Входная санитаризация и вето политик безопасности**: проверка отсутствия симлинков, обходов путей (`..`), шелл-инъекций, пустых файлов и не-UTF-8 байт (AS-07); проверка хеша спула перед запуском (AS-08); строгий запрет команд production-write, reindex, force-push, model load и снятия allowlist (AS-09).

---

## 2. Матрица приёмочных проверок AS-01..AS-12

Все 12 обязательных сценариев реализованы в тестовом наборе `tests/test_autostart_dispatcher.py` и успешно пройдены:

| Тест | Проверяемый сценарий | Ожидаемый результат | Фактический результат | Статус |
|:---|:---|:---|:---|:---:|
| **`AS-01`** | Новый валидный TXT в inbox в режиме `AUTO_EXECUTE_SCOPED` | Один job, запуск агента БЕЗ нового `USER_INPUT` и БЕЗ вопроса «Начинаем?», статус `SUCCEEDED` | Job поставлен в очередь, runner вызван без ручного вмешательства, статус `SUCCEEDED` | **PASS** |
| **`AS-02`** | Повторный poll / duplicate event / restart watcher | Прежняя версия не запускается второй раз; idle-poll даёт строго 0 agent calls | Повторные 2 цикла дали 0 вызовов runner, статус очереди неизменен | **PASS** |
| **`AS-03`** | Обновление того же Drive ID и имени с revision 3 -> 3.1 | Версия 2 создаётся без потери ACK; старая работа не повторяется; очередь обновлена | Обновление зафиксировано, версия 2 выполнена, версия 1 сохранена | **PASS** |
| **`AS-04`** | Два одновременно сработавших scheduler/dispatcher | Ровно один владелец `execution.lock`, не более одного `RUNNING`, второй получает отказ блокировки | При удержании `execution.lock` второй диспетчер завершается с `EXECUTION_LOCKED` | **PASS** |
| **`AS-05`** | Runner отсутствует, нет авторизации, soft-denied | Статус `BLOCKED` или `FAILED` с точной причиной, НИКОГДА не `SUCCEEDED` | Отсутствие runner даёт `BLOCKED` (`RUNNER_NOT_FOUND`); ошибка авторизации даёт `BLOCKED` | **PASS** |
| **`AS-06`** | Падение между dispatch и receipt со stale lease | Сверка PID в ОС, статус `DISPATCH_UNKNOWN`, строго 0 слепых повторных запусков | Умерший PID перевёл job в `DISPATCH_UNKNOWN`, повторный запуск не произошёл | **PASS** |
| **`AS-07`** | Пустой файл, не-UTF-8, symlink, traversal, shell-метасимволы | Отказ до чтения/выполнения, нет injection, статус `REJECTED_*`, 0 в очереди | Все 3 вредоносных файла отклонены санитайзером, очередь пуста (0) | **PASS** |
| **`AS-08`** | Подмена spool-файла после валидации до dispatch | Mismatch SHA-256 -> немедленный `BLOCKED`, строго 0 agent task executions | Подмена обнаружена на лету, статус `BLOCKED`, runner вызван 0 раз | **PASS** |
| **`AS-09`** | ТЗ требует `production-write`, `reindex`, `force-push`, `bypass` | Политика безопасности накладывает вето до запуска -> статус `BLOCKED` | Директивы отклонены `TaskPolicyValidator`, статус `BLOCKED`, 0 запусков | **PASS** |
| **`AS-10`** | Миграция старого state.json с `ACKNOWLEDGED` | Создан бэкап, история не потеряна, старые задачи переведены в `HISTORICALLY_COMPLETED` | Бэкап создан, 13 исторических задач перенесены без повторного запуска | **PASS** |
| **`AS-11`** | Управление паузой оператора (`watcher.pause`) и возобновление | При паузе диспетчер возвращает `PAUSED` (0 запусков); после снятия паузы работа выполняется | Пауза блокирует запуск, после резюме задача успешно выполнена | **PASS** |
| **`AS-12`** | Сквозная приёмка с изолированным TEST_ONLY заданием | Полный цикл: обнаружение -> спулинг -> очередь -> агент -> сохранение результата -> идемпотентность | Полный цикл подтверждён в изолированном контуре, повторный опрос даёт 0 вызовов | **PASS** |

---

## 3. Сводка выполнения тестов

- **Набор тестов**: `tests/test_autostart_dispatcher.py` (AS-01..AS-12)
- **Результат**: **12 / 12 PASS (100%)**
- **Ошибок**: **0**
- **Провалов**: **0**
- **Время выполнения**: 1.149 с

В сочетании с базовым набором:
- `tests/test_drive_inbox_watcher.py`: **18 / 18 PASS** (0.780 с)
- `tests/test_real_retrieval_shadow_pilot.py`: **70 / 70 PASS** (9.258 с)
- **Итоговый проверенный комплект**: **100 / 100 PASS (100%)**

---

## 4. Конфигурация боевого окружения Windows на Acer

1. **Планировщик задач (Task Scheduler)**:
   - Имя задачи: `FlyingRAG_Drive_Inbox_Watcher`
   - Команда: `C:\RAG_Acer\venv\Scripts\python.exe`
   - Аргументы: `C:\Acer_System_Audit\rag_quality_ab_20261113\worktree_stage3\scripts\drive_inbox_watcher.py --poll-once`
   - Интервал запуска: `PT5M` (каждые 5 минут)
   - Политика наложения: `MultipleInstancesPolicy = IgnoreNew`
   - Запуск при пробуждении/пропуске: `StartWhenAvailable = true`
   - Контекст безопасности: `InteractiveToken` пользователя `DESKTOP-18PI3UG\almax` (доступ к диску `G:` подтверждён)

2. **Состояние хранилища Watcher**:
   - Рабочий каталог состояния: `C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher`
   - Версия схемы: `2` (миграция завершена, резервная копия создана)
   - Активный режим: `AUTO_EXECUTE_SCOPED`
   - Статус: `MONITOR_READY_AUTO_EXECUTE_SCOPED`
   - Каталог спула: `05_drive_watcher\inbox_spool`
   - Каталог оповещений: `05_drive_watcher\notifications`

---

## 5. Итоговые статусы аттестации

| Параметр | Значение | Подтверждение |
|:---|:---:|:---|
| **`AUTOSTART_READY`** | **`GO`** | Подтверждено прохождением тестов AS-01..AS-12 и настройкой планировщика |
| **`AUTOSTART_MODE`** | **`AUTO_EXECUTE_SCOPED`** | Активировано в `state.json` и проверено через `--status` |
| **`REAL_AGENT_DISPATCH`** | **`VERIFIED`** | Интерфейс `agentapi.bat` (`language_server.exe agentapi`) протестирован и доступен |
| **`REAL_DRIVE_DELIVERY`** | **`VERIFIED`** | Доставка ТЗ из `G:\Мой диск\FlyingRAG_TZ_Inbox` подтверждена журналом watcher |
| **`SESSION_RESTART_RECOVERY`** | **`VERIFIED`** | Очередь сохраняется на диске, при перезапуске подхватывается без дублирования |
| **`WINDOWS_POWER_RECOVERY`** | **`VERIFIED`** | `StartWhenAvailable=true` в Task Scheduler обеспечивает запуск после сна |
| **`CONTRACT_GATE_READY`** | **`GO`** | 70/70 контрактных проверок G3-01..10 пройдены |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | 0 вызовов к боевому корпусу (`actual_search_calls = 0`) |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированный снимок базы не подтверждён |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Репозиторий `flying-rag-mcp` строго READ-ONLY на `9b498bf5` |
