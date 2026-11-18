# Отчёт о готовности к пост-фикс пилоту: ТЗ-015 Rev 1.2 (Stage 4.2.9 / OUTPUT AND RANK GUARD)

**Документ**: Отчёт об устранении дефектов вывода в stdout, строгой канонической идентификации рангов, полной санации переменных окружения, разделении механического и доказательного успеха и верификации тестовой матрицы G15-R12-01..10  
**Техническое задание**: [FR-TZ-20261118-015_REV1_2_OUTPUT_AND_RANK_GUARD_3dbe9de9_f8947760.txt](file:///G:/Мой%20диск/FlyingRAG_TZ_Inbox/FR-TZ-20261118-015_REV1_2_OUTPUT_AND_RANK_GUARD_3dbe9de9_f8947760.txt)  
**Редакция**: Редакция 1.2 от 18 ноября 2026 года | Размер: 17 234 байта, UTF-8 | SHA-256: `dc58fe98eb22fdfb9ae1c4ffb3b8fe7feef364d2931a7f05c6c0e527fcbbfe8d`  
**Ветка аудита**: `audit/stage4-2-verification`  
**Коммит кода и тестов (Phase A)**: [`04fe8d22ab4c6e2680a0d345b88b9967dbb8467d`](https://github.com/Kritik35/flying-rag-mcp/commit/04fe8d22ab4c6e2680a0d345b88b9967dbb8467d) (Tree: `c98032ad03e2...`, Parent: `f89477608d7e...`)  
**Родительский коммит отчётов**: [`f89477608d7e46fb331590fa7b2cccb584a5c64f`](https://github.com/Kritik35/flying-rag-mcp/commit/f89477608d7e46fb331590fa7b2cccb584a5c64f) (Tree: `820a80cb66ee...`)  
**Официальный вердикт**: **`WAITING_OPERATOR_SEARCH_APPROVAL` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `HARNESS_FAIL_CLOSED_VERIFIED: YES` / `TEST_SUITE_G15_R12: 10/10 PASS` / `TEST_SUITE_P15: 10/10 PASS` / `REGRESSION_014: 42/42 PASS` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**

---

## 1. Устранение замечаний ТЗ-015 Rev 1.2 (P0-R1 .. P1-Q1)

### 1.1. P0-R1: Полное исключение сырых текстов корпуса из CLI stdout / stderr / журналов
- **Проблема**: В `tests/postfix_pilot_harness_015.py` после `save_separated_results()` вызывался `print(json.dumps(res, indent=2))` с полными сырыми хитами поиска (`raw_result`), что приводило к попаданию необработанных фрагментов в консоль, транскрипт и логи сеанса.
- **Исправление**:
  1. Функция `save_separated_results()` формирует уникальный путь для каждого прогона с уникальным UUID: `postfix_pilot_raw_results_{task_id}_{timestamp}_{uuid}.json`, исключая перезапись предыдущих данных.
  2. Из публичного отчёта полностью удаляются поля `raw_result`; цитаты `top_hit.snippet` принудительно ограничиваются $\le 200$ символами и очищаются от служебных меток.
  3. В `main()` (для `--test-machinery` и `--execute-approved-pilot`) в консоль выводится **исключительно санированный отчёт** (`sanitized_report`), а также SHA-256 хеш и безопасный путь к приватному файлу в temp.
  4. Проведено тестирование с маркером `SECRET_FIXTURE_SENTINEL_015`: подтверждено, что маркер присутствует только в закрытом файле temp и отсутствует в stdout, stderr и Git JSON (тесты G15-R12-01, G15-R12-02).

### 1.2. P0-R2: Строгая каноническая идентификация рангов (`compare_ranks`)
- **Проблема**: В `compare_ranks()` использовался предикат `any(bool(x) for x in ranks)`, из-за чего список с валидным первым хитом и пустым вторым хитом (`[{"chunk_id":"c1"}, {"text":"unidentified"}]`) ошибочно получал `True` (ложноположительный PASS).
- **Исправление**:
  1. Реализована функция `extract_canonical_id()`, формирующая строгий составной идентификатор вида `doc_id|edition|clause|primary_id` либо чистый `chunk_id`.
  2. Любые пустые строки, псевдо-идентификаторы (`"None"`, `"null"`, `"undefined"`, `"{}"`, `"[]"`) или невалидные типы строго возвращают `None`.
  3. В `compare_ranks()`:
     - Обязательно проверяется, что **каждый** элемент списка содержит валидный идентификатор (`all()`).
     - Проверяется отсутствие дубликатов идентификаторов внутри одного списка (`len(set(ids)) == len(ids)`).
     - Списки сравниваются поэлементно: порядок, идентификаторы и нормализованная полезная нагрузка должны быть строго идентичны.

### 1.3. P0-R3: Полная очистка переменных `FLYING_RAG_*`
- **Проблема**: В `execute_bounded_search()` сохранялись наследуемые переменные `FLYING_RAG_CONFIG`, `FLYING_RAG_SHADOW_EIG`, `FLYING_RAG_SHADOW_LOG_PATH` и `FLYING_RAG_SHADOW_CONTROL_FILE`, что создавало риск утечки внешних путей управления от родительского процесса.
- **Исправление**:
  1. Из `child_env` перед запуском дочернего процесса удаляются **все** переменные с префиксом `FLYING_RAG_`:
     ```python
     child_env = {k: v for k, v in os.environ.items() if not k.startswith("FLYING_RAG_")}
     ```
  2. В дочерний процесс передаются исключительно явно проверенные параметры: `FLYING_RAG_CONFIG` (внутри temp), `FLYING_RAG_SHADOW_EIG` ("0" или "1"), `FLYING_RAG_SHADOW_LOG_PATH` (внутри temp).
  3. В `shadow_pilot_worker.py` на старте `main()` выполняется повторная очистка `os.environ` от любых переменных `FLYING_RAG_*`, после чего применяются только аргументы командной строки.
  4. Проверено тестом G15-R12-06: установка в parent env внешнего `FLYING_RAG_SHADOW_CONTROL_FILE` полностью игнорируется и не приводит к созданию файлов на диске.

### 1.4. P1-Q1: Разделение механического успеха стенда и доказательного качества нормы
- **Проблема**: Статус `evidence_complete` выставлялся по наличию любого текста, не проверяя совпадение нормативного документа, редакции, пункта и полноту перечислений. Счётчик реальных вызовов увеличивался до запуска дочернего процесса.
- **Исправление**:
  1. Счётчик `actual_corpus_search_calls` увеличивается **строго после фактического успешного запуска дочернего процесса** (`res.get("spawned", False)`).
  2. Разработана функция `evaluate_normative_evidence()` с раздельными метриками:
     - `TARGET_DOC_MATCH`: соответствие искомому документу (СП 7.13130, СП 60.13330).
     - `TARGET_EDITION_MATCH`: строгое соответствие целевому году редакции (для Q088 строго 2020 год; редакции без года или с иным годом отклоняются).
     - `TARGET_CLAUSE_MATCH`: соответствие искомому пункту (6.4, 6.10, 7.1.1).
     - `HAS_PAGE_OR_VALID_LOCATOR`: наличие страницы/локатора/списка родителей.
     - `FULL_CLAUSE_EVIDENCE`: проверка целостности пункта 6.10 (наличие перечислений EI 60 / EI 15, отсутствие маркера `EVIDENCE_PARTIAL`, отсутствие захвата заголовка раздела 7).
     - `SOURCE_FIDELITY`: соответствие текста первоисточнику.
     - Неопределённые значения маркируются как `UNKNOWN`, без автоматической подмены на `PASS`.
  3. Механический вердикт пары (`MECHANICAL_PAIR_OK`: совпадение кодов возврата, рангов, полезной нагрузки, валидность теневого адаптера) отделён от содержательной оценки качества нормы.

### 1.5. Разграничение архитектуры мониторинга Google Drive
- **Штатный мониторинг Acer**: Задача планировщика заданий Windows `FlyingRAG_Drive_Inbox_Watcher` с 5-минутным интервалом опроса сохранена в исходном виде, обеспечивает автозапуск и восстановление после перезагрузки.
- **Интерактивный сессионный демон**: Скрипт `watch_drive_tz.py --daemon` (Task ID: `task-20723`) с 5-секундным интервалом является временным вспомогательным процессом текущей рабочей сессии для оперативного обнаружения файлов ТЗ.

---

## 2. Результаты верификации матриц тестов

### 2.1. Матрица ТЗ-015 Rev 1.2 (G15-R12-01 .. G15-R12-10)
Тестовый сьют [tests/test_postfix_pilot_fail_closed_015_rev1_2.py](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/tests/test_postfix_pilot_fail_closed_015_rev1_2.py) выполнен полностью (**10/10 PASS**, 9.7 с):

| Тест | Проверяемое требование | Результат | Подтверждение |
|:---|:---|:---:|:---|
| **G15-R12-01** [P0] | CLI синтетический success с маркером `SECRET_FIXTURE_SENTINEL_015` | **PASS** | stdout/stderr/Git JSON чисты; raw в temp содержит маркер; exit 0, статус `SYNTHETIC_MACHINERY_VERIFIED`. |
| **G15-R12-02** [P0] | CLI синтетический failure с маркером | **PASS** | Ни один канал отчётности не выводит raw/маркер; exit != 0, статус `HALTED_AFTER_FAILURE`. |
| **G15-R12-03** [P0] | Два последовательных прогона стенда | **PASS** | Приватные raw имеют уникальные имена с UUID/таймстемпом и независимые SHA-256, не перезаписывают друг друга. |
| **G15-R12-04** [P0] | Пара с valid hit1 + hit2 без ID (`[{"chunk_id":"c1"},{"text":"..."}]`) | **PASS** | `compare_ranks=False`; общий `FAIL`, 0 вызовов следующей пары (fail-fast). |
| **G15-R12-05** [P0] | Дубликаты ID, псевдо-ID ('None', 'null', '{}'), чужой edition | **PASS** | Строго отклоняются (`compare_ranks=False`); валидный список даёт `True`. |
| **G15-R12-06** [P0] | Запрещённые `FLYING_RAG_*` overrides в parent env (CONTROL_FILE, DB, CONFIG) | **PASS** | Дочерний процесс получает только проверенные пути; 0 внешних записей. |
| **G15-R12-07** [P0] | Сбой worker / empty retrieval / timeout / observer error | **PASS** | Fail-fast сохранён; `max spawned = 1` для первого сбоя. |
| **G15-R12-08** [P1] | Доказательная схема нормы (wrong clause/edition/обрезанный EI15) | **PASS** | `QUALITY_VERIFIED=False`, `FULL_CLAUSE_EVIDENCE=FAIL`; механическая пара отделена от качества. |
| **G15-R12-09** [P1] | Регрессионная верификация инвариантов preflight и scope | **PASS** | Все префлайт-чеки, scope и хеши соответствуют контрактам этапа 4.2.8/4.2.9. |
| **G15-R12-10** [P1] | Отчётность статусов (contract/native/synthetic/live) | **PASS** | `actual_search_calls=0`; `LIVE_GATE=NOT_EXECUTED`; `CONSISTENT_SNAPSHOT=UNVERIFIED`; `MODEL_INDEX_IDENTITY=UNVERIFIED`. |

### 2.2. Регрессионные наборы тестов
1. **Матрица Rev 1.1** ([tests/test_postfix_pilot_fail_closed_015.py](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/tests/test_postfix_pilot_fail_closed_015.py)): **10/10 PASS** (6.7 с).
2. **Набор ТЗ-014** ([tests/test_retrieval_clause_edition_014.py](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/tests/test_retrieval_clause_edition_014.py)): **42/42 PASS** (47.9 с).

---

## 3. Официальные вердикты гейтов (Rev 1.2)

| Гейт | Вердикт | Обоснование |
|:---|:---:|:---|
| **`STATUS`** | **`WAITING_OPERATOR_SEARCH_APPROVAL`** | Все замечания P0-R1..P0-R3 и P1-Q1 устранены, матрица G15-R12 пройдена (10/10), ожидается санкция оператора. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Реальных вызовов к корпусу не выполнялось (строго 0). |
| **`HARNESS_FAIL_CLOSED_VERIFIED`** | **`YES`** | Утечка в stdout закрыта, строгий rank identity подтверждён, очистка окружения завершена. |
| **`ISOLATED_COPY_VERIFIED`** | **`YES`** | Изолированная копия проверена через `check_readonly_scope` и `validate_pilot_config`. |
| **`CONSISTENT_SNAPSHOT`** | **`UNVERIFIED`** | Последовательное копирование компонентов в ТЗ-011. |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Совпадение размерности 1024 не доказывает идентичности весов исторического индекса. |
| **`PILOT_NATURE`** | **`DIAGNOSTIC_PILOT_ONLY`** | Сертификация для production заблокирована до подтверждения снимка и модели. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 4. Состояние готовности к 6 поисковым вызовам

Стенд полностью защищён по схеме fail-closed, утечки данных в консоль устранены, ранжирование защищено от ложных пропусков, очистка окружения гарантирует отсутствие внешних записей.

В соответствии с ТЗ-015 Rev 1.2 исполнитель **останавливает выполнение** со статусом `WAITING_OPERATOR_SEARCH_APPROVAL` и запрашивает согласие оператора:

> **Формулировка запроса оператору**:
> *«Разрешаю ТЗ-015 выполнить ровно 6 реальных поисковых вызовов Q004, Q010, Q088-2020 (3 пары EIG OFF/ON) на проверенной существующей изолированной копии, без любых изменений production».*
