# Отчёт о готовности к пост-фикс пилоту: ТЗ-015 Rev 1.1 (Stage 4.2.9 / FAIL-CLOSED SAFETY ERRATA)

**Документ**: Отчёт об устранении дефектов изоляции, очистке наследуемого окружения, реализации обязательного fail-fast останова, защите от ложных PASS и верификации тестовой матрицы P15-01..P15-10  
**Техническое задание**: [FR-TZ-20261118-015_REV1_1_HARNESS_FAIL_CLOSED_e52c3164_a3b830f1.txt](file:///G:/Мой%20диск/FlyingRAG_TZ_Inbox/FR-TZ-20261118-015_REV1_1_HARNESS_FAIL_CLOSED_e52c3164_a3b830f1.txt)  
**Редакция**: Редакция 1.1 от 18 ноября 2026 года | Размер: 18 289 байт, UTF-8 | SHA-256: `0b527f361ca747fdf6479c325008ac8130e5c3f19982f640d671ef9d046060bd`  
**Ветка аудита**: `audit/stage4-2-verification`  
**Коммит кода и тестов (Phase A)**: [`3dbe9de9887cd087ea53920d0761b0e914f467b2`](https://github.com/Kritik35/flying-rag-mcp/commit/3dbe9de9887cd087ea53920d0761b0e914f467b2) (Tree: `9d50c22fc19f...`, Parent: `a3b830f137df...`)  
**Родительский коммит отчётов**: [`a3b830f137df8caf233e9dd20991cbdb4c84d421`](https://github.com/Kritik35/flying-rag-mcp/commit/a3b830f137df8caf233e9dd20991cbdb4c84d421) (Tree: `ac0be41e2b39...`)  
**Официальный вердикт**: **`WAITING_OPERATOR_SEARCH_APPROVAL` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `HARNESS_FAIL_CLOSED_VERIFIED: YES` / `TEST_SUITE_P15_01_10: 10/10 PASS` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**

---

## 1. Устранение выявленных замечаний ТЗ-015 Rev 1.1

### 1.1. P0-1: Проверка эффективного scope и очистка окружения дочернего процесса
- **Проблема**: В `preflight_check()` выполнялся поиск подстроки по YAML-файлу без проверки реального `check_readonly_scope`. Дочерний процесс `shadow_pilot_worker.py` наследовал `child_env = dict(os.environ)`, где переменная `FLYING_RAG_METADATA_DB` (имеющая приоритет в `server._get_shadow_adapter()`) могла направить теневой адаптер EIG к боевой базе данных.
- **Исправление**:
  1. В `preflight_check()` встроен вызов реального `check_readonly_scope(target_config, backend_online=True, allowed_fixture_root=target_root)` и `validate_pilot_config(target_config)`.
  2. Добавлен анализ переменной `os.environ.get("FLYING_RAG_METADATA_DB")`: при её указании вне изолированного временного каталога префлайт немедленно возвращает `STOP_SCOPE`, блокируя любые вызовы.
  3. В `execute_bounded_search()` реализована строгая очистка окружения: перед запуском дочернего процесса удаляются все `FLYING_RAG_*` переменные, кроме явно разрешённых (`CONFIG`, `SHADOW_EIG`, `SHADOW_LOG_PATH`, `SHADOW_CONTROL_FILE`). Переменные `FLYING_RAG_METADATA_DB`, `FLYING_RAG_LANCEDB_PATH`, `FLYING_RAG_TABLE_PARQUET` принудительно вычищаются из `child_env`.
  4. В `shadow_pilot_worker.py` при получении `--config-path` также гарантированно удаляются `FLYING_RAG_METADATA_DB` и пути хранилища.

### 1.2. P0-2: Обязательный Fail-Fast останов после первого сбоя
- **Проблема**: Стенд продолжал последующие вызовы при ошибках, таймаутах, ненулевых кодах завершения или несовпадении рангов, выполняя сравнение лишь после завершения всех шести обращений.
- **Исправление**:
  1. Реализован немедленный останов (`fail-fast`): если любой единичный вызов завершается с ошибкой, ненулевым кодом выхода, таймаутом, error envelope (`is_error_payload`), пустой выдачей или нарушением неизменности боевой базы — цикл **немедленно прерывается** (`break`), последующие дочерние процессы **не запускаются**.
  2. Ведутся раздельные строгие счётчики: `planned_calls_count = 6`, `attempted_calls`, `spawned_calls`, `completed_calls`, `actual_corpus_search_calls`.
  3. Парное сравнение (OFF vs ON) выполняется **сразу после завершения ON-вызова**. При нарушении эквивалентности рангов или нормализованной полезной нагрузки стенд останавливается, не переходя к следующей паре запросов.

### 1.3. P0-3: Исключение ложных PASS при ненулевом коде завершения, пустой выдаче и ошибках EIG
- **Проблема**: При `exitcode != 0` и непустом stdout код мог вернуть `success: true`. Пустые списки `[]` при `compare_ranks` давали ложное равенство. Статистика теневого адаптера EIG не проверялась.
- **Исправление**:
  1. В `execute_bounded_search()` ненулевой код завершения (`exitcode != 0`) строго и безусловно возвращает `success: false` с кодом ошибки `NONZERO_EXIT_NO_GO`, даже если stdout содержал валидный JSON.
  2. В `compare_ranks()` пустые списки (`[] == []`) и результаты без физических идентификаторов (`chunk_id`, `id`, `parent_ids`) строго отклоняются (`return False`).
  3. Разделены статусы: `search_executed` (код 0), `retrieval_match` (найдены валидные ID), `evidence_complete` (присутствует текст и реквизиты нормы).
  4. Для вызова с EIG ON проверяется телеметрия фонового адаптера (`shadow_stats`): обязательно `submitted > 0`, `processed >= submitted`, `errors == 0`, `dropped == 0`. При несоблюдении — статус `FAIL_SHADOW_OBSERVER` и немедленный останов стенда.

### 1.4. P1-1: Разделение сырых текстов и публичного отчёта
- **Проблема**: Полные тексты нормативных документов сохранялись в отслеживаемый репозиторием файл `reports/postfix_pilot_results_015.json`.
- **Исправление**:
  1. Реализована функция `save_separated_results()`: полные сырые ответы сохраняются **только во временный файл** внутри temp (`postfix_pilot_raw_results_015.json`), вычисляется их 64-символьный SHA-256 хеш.
  2. Публичный отчёт в репозитории содержит только очищенные метаданные, краткие цитаты (до 200 символов), идентификаторы, статус и хеш `raw_results_sha256`.

### 1.5. Дополнительная задача: Фоновый монитор Google Drive (Background Task)
- Разработан автономный скрипт [scripts/watch_drive_tz.py](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/scripts/watch_drive_tz.py).
- Запущен в качестве фонового процесса-демона (Antigravity background daemon task):
  * Отслеживает каталог `G:\Мой диск\FlyingRAG_TZ_Inbox` с интервалом 5 секунд.
  * При обнаружении нового файла или изменении SHA-256 автоматически считывает текст, извлекает заголовок и параметры ТЗ, записывает событие в `tz_inbox_events.log` и сохраняет снимок в `tz_inbox_monitor_state.json`.

---

## 2. Результаты верификации тестовой матрицы (P15-01 .. P15-10)

Создан и выполнен специализированный тестовый набор [tests/test_postfix_pilot_fail_closed_015.py](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/tests/test_postfix_pilot_fail_closed_015.py). Все 10 сценариев успешно пройдены (**10/10 PASS**, время выполнения: 6.5 с):

| Тест | Проверяемое требование | Результат | Обоснование |
|:---|:---|:---:|:---|
| **P15-01** | `FLYING_RAG_METADATA_DB` в host env указывает на production | **PASS** | `preflight_check` возвращает `STOP_SCOPE`, `attempted_calls=0`, `spawned_calls=0`. |
| **P15-02** | YAML содержит production alias, UNC или traversal (`..`) | **PASS** | Scope guard блокирует конфигурацию со статусом `STOP_SCOPE`, 0 вызовов. |
| **P15-03** | Первый worker падает с ошибкой / таймаутом | **PASS** | `fail-fast`: `attempted=1`, `spawned=1`, `completed=0`, вызовы 2..6 не запускаются. |
| **P15-04** | OFF и ON первой пары возвращают разные ранги | **PASS** | Сравнение первой пары даёт `FAIL`, вторая пара (Q010) не запускается. |
| **P15-05** | Child завершился с кодом 1, но stdout содержит `success: true` | **PASS** | Возвращается `NONZERO_EXIT_NO_GO`, `success=False`, немедленный останов. |
| **P15-06** | Вызовы возвращают пустые результаты `result: []` | **PASS** | `retrieval_match=False`, общий диагностический PASS запрещён, немедленный останов. |
| **P15-07** | ON-observer отсутствует, имеет ошибки или `processed < submitted` | **PASS** | Фиксируется `FAIL_SHADOW_OBSERVER`, останов без запуска следующей пары. |
| **P15-08** | Хиты без реальных chunk/parent IDs | **PASS** | `compare_ranks` строго отклоняет такие результаты (`return False`). |
| **P15-09** | Сквозной синтетический прогон 6 вызовов | **PASS** | Все 6 вызовов успешны, метка `SYNTHETIC_MACHINERY_ONLY`, `actual_calls=0`, `live_gate=NOT_EXECUTED`. |
| **P15-10** | Защита от утечки сырых текстов в Git | **PASS** | Полный raw сохранён в temp с SHA-256, публичный отчёт содержит только excerpts <= 200 символов. |

Регрессионный набор `tests/test_retrieval_clause_edition_014.py` также полностью зелёный (**42/42 PASS**, 47.3 с).

---

## 3. Официальные вердикты гейтов (Rev 1.1)

| Гейт | Вердикт | Обоснование |
|:---|:---:|:---|
| **`STATUS`** | **`WAITING_OPERATOR_SEARCH_APPROVAL`** | Все P0 устранены, матрица P15-01..10 пройдена (10/10), ожидается санкция оператора. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу выполнено: строго 0. |
| **`HARNESS_FAIL_CLOSED_VERIFIED`** | **`YES`** | Scope check, очистка env, fail-fast, строгие коды выхода и изоляция raw подтверждены. |
| **`ISOLATED_COPY_VERIFIED`** | **`YES`** | Изолированная копия проверена через `check_readonly_scope` и `validate_pilot_config`. |
| **`CONSISTENT_SNAPSHOT`** | **`UNVERIFIED`** | Последовательное копирование компонентов в ТЗ-011. |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Совпадение размерности 1024 не доказывает идентичности весов исторического индекса. |
| **`PILOT_NATURE`** | **`DIAGNOSTIC_PILOT_ONLY`** | Сертификация для production заблокирована до подтверждения снимка и модели. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 4. Запрос санкции оператора на проведение 6 поисковых вызовов

Все защитные критерии ТЗ-015 Rev 1.1 выполнены и верифицированы на уровне кода и отрицательных тестов. В соответствии с разделом 6 ТЗ-015 Rev 1.1 исполнитель **останавливает выполнение** со статусом `WAITING_OPERATOR_SEARCH_APPROVAL` и запрашивает согласие оператора:

> **Формулировка запроса оператору**:
> *«Разрешаю ТЗ-015 выполнить ровно 6 реальных поисковых вызовов Q004, Q010, Q088-2020 (3 пары EIG OFF/ON) на проверенной существующей изолированной копии, без любых изменений production».*
