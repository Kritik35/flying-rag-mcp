# Stage 4.2.8 — PILOT-GATE-01 Revision 3: Pre-Execution Gate Acceptance Report

**Документ**: Отчёт о приёмке ужесточённого предохранительного гейта PILOT-GATE-01 Revision 3  
**ТЗ**: `FR-TZ-20261117-006` / PILOT-GATE-01 Revision 3 + AUTO-START-01 (`1cbd6411e21298d9ec8594f77e3c03fe6eff7be80418799423a378de5e0e86c1`, Редакция 3.1 от 2026-11-17)  
**Google Drive ID**: `1SZ2oPnmydcxFQFEzF4F8jzjvLO_K5OtR`  
**Дата**: 17 ноября 2026 года  
**Статус документа**: **CONTRACT_GATE_READY: GO / REAL_PILOT: NOT_EXECUTED**  
**Проверенный коммит кода (tested code anchor)**: [`238ae2668aa1985996c439d4bffc428572a18a44`](https://github.com/Kritik35/flying-rag-mcp/commit/238ae2668aa1985996c439d4bffc428572a18a44)  
**Tree SHA кода**: `6f78e3da04700a02c9f993d8a8c9363f8fb42b51`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`dd54dfcda15a5ea39a93513286490d8bc9487588`](https://github.com/Kritik35/flying-rag-mcp/commit/dd54dfcda15a5ea39a93513286490d8bc9487588) (Tree: `1c96829784b0a2ca218d2e6c325f014dd173b387`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`f009cfe484c09aa2838ff5feb23614c6db0330d3`](https://github.com/Kritik35/flying-rag-mcp/commit/f009cfe484c09aa2838ff5feb23614c6db0330d3) (Tree: `8285ddf70565e7e1d6712381a2589be655e30986`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `<PRODUCTION_DB_METADATA>` (размер: 1,485,103,104 байт, WAL: 0 байт, не изменялась)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Незакоммиченные изменения (dirty paths)**: **СТРОГО 0**  

---

## 1. Резюме ужесточения требований Revision 3

В рамках ТЗ `FR-TZ-20261117-006` Revision 3 полностью устранены замечания к предохранительному гейту и реализован полный комплект негативных контрактных проверок G3-01..G3-10:

1. **P0-A: Строгие целочисленные счётчики заголовка манифеста (`validate_query_manifest`)**:
   - В режиме `expected_count=105` поля `total_queries == 105`, `normative_count == 80`, `adversarial_count == 25` строго обязательны.
   - Значения проверяются строгой проверкой типа `type(v) is int` (булевы значения `True`/`False` строго запрещены).
   - При отсутствии счётчиков, неверном типе (`bool`, `str`, `float`), несовпадении с фактическим числом элементов в массиве или нарушении профиля 80/25 валидация немедленно завершается отказом (`MANIFEST_INVALID_HEADER_COUNTS`, `MANIFEST_INVALID_HEADER_TYPES`, `MANIFEST_PROFILE_MISMATCH`).

2. **P0-B: Доказательство владения процессом на уровне ОС (`verify_process_termination_safety`)**:
   - Положительная верификация (`safe = True`) теперь **строго требует** наличия валидной, непустой записи `owned_process_record` с числовыми `pid` и `create_time`/`start_time`.
   - Несовпадение PID или времени запуска (`abs(actual - record) > 2.0s`) безусловно возвращает `safe = False` и причину отказа (`OWNED_RECORD_PID_MISMATCH`, `OWNED_RECORD_START_TIME_MISMATCH`).
   - Исключено тихое подавление исключений `(ValueError, TypeError)`.

3. **P0-C: Корректировка формы решения оператора**:
   - Удалены рекомендации внешних непроверенных путей (например, `<PRODUCTION_DIR>/isolated_pilot_data`), нарушавших `check_readonly_scope`.
   - Введено обязательное использование зарегистрированного временного каталога (`register_verified_fixture_root`).
   - Чётко разграничены состояния `SNAPSHOT_FILES_PRESENT` и `CONSISTENT_SNAPSHOT_VERIFIED`.

4. **Разграничение режимов и метрик серии**:
   - В результатах пилота строго разделяются режимы `SMOKE_LEGACY_8` (8 запросов по умолчанию) и `FULL_MANIFEST_105` (канонический манифест 105 запросов).
   - При ограничении `max_queries < total_planned` серия явно маркируется как `PARTIAL`.
   - Статус `FULL_105_GO` и `full_105_go_eligible` выставляются **исключительно** при полном прогоне канонического манифеста 105 запросов (210 вызовов) на верифицированном хранилище.

---

## 2. Матрица негативных тестов G3-01..G3-10

Все 10 обязательных негативных тестов Revision 3 реализованы в `tests/test_real_retrieval_shadow_pilot.py` и успешно пройдены:

| Тест | Проверяемый сценарий | Ожидаемый результат | Фактический результат | Статус |
|:---|:---|:---|:---|:---:|
| **`G3-01`** | Манифест 105 запросов без `normative_count` / `adversarial_count` | Отказ `MANIFEST_INVALID_HEADER_COUNTS`, статус `CONFIG_INVALID`, 0 вызовов | Отказ `MANIFEST_INVALID_HEADER_COUNTS`, вердикт `BLOCKED`, 0 вызовов | **PASS** |
| **`G3-02`** | Счётчики заголовка с булевым типом (`True`/`False`) | Отказ `MANIFEST_INVALID_HEADER_TYPES`, статус `CONFIG_INVALID`, 0 вызовов | Булевы счётчики строго отклонены, вердикт `BLOCKED`, 0 вызовов | **PASS** |
| **`G3-03`** | Манифест на 105 элементов, но распределение 79/26 вместо 80/25 | Отказ `MANIFEST_PROFILE_MISMATCH`, статус `CONFIG_INVALID`, 0 вызовов | Несоответствие профиля 80/25 отклонено до запуска, 0 вызовов | **PASS** |
| **`G3-04`** | Нестроковые типы в `total_queries` / `normative_count` в нестрогом режиме | Отказ `MANIFEST_INVALID_HEADER_TYPES`, статус `CONFIG_INVALID`, 0 вызовов | Все нецелочисленные типы строго отклонены | **PASS** |
| **`G3-05`** | `verify_process_termination_safety` без `owned_process_record` | `safe = False`, отказ `OWNED_RECORD_REQUIRED`, 0 сигналов ОС | `safe = False`, `OWNED_RECORD_REQUIRED` зафиксирован | **PASS** |
| **`G3-06`** | Некорректные типы `create_time` в `owned_process_record` (`dict`, `None`, мусор) | `safe = False`, отказ `OWNED_RECORD_START_TIME_INVALID`, без тихого пропуска | Все некорректные типы приводят к отказу `safe = False` | **PASS** |
| **`G3-07`** | Совпадение PID/exe, но расхождение PID/времени в `owned_process_record` или чужой порт | `safe = False`, `OWNED_RECORD_PID_MISMATCH`, `OWNED_RECORD_START_TIME_MISMATCH`, `PORT_8089_IN_USE_BY_FOREIGN_PROCESS` | Отказ по всем веткам валидации, 0 сигналов завершения | **PASS** |
| **`G3-08`** | Контролируемый собственный процесс + валидный `owned_process_record` | `safe = True`, статус `PROCESS_IDENTITY_VERIFIED`, без вызова kill/terminate | Собственный процесс успешно верифицирован | **PASS** |
| **`G3-09`** | Форма оператора предлагает внешний путь вне системного temp | Отказ `check_readonly_scope` (`BLOCKED_READONLY_NOT_PROVEN`), вердикт `BLOCKED`, 0 вызовов | Запуск строго заблокирован с 0 поисковых вызовов | **PASS** |
| **`G3-10`** | 8-запросный фоллбек или `max_queries=3` не получают `FULL_105_GO` | Режим `SMOKE_LEGACY_8` / `PARTIAL`, `full_105_go_eligible = False` | Неполные прогоны строго лишены права на статус полного ГО | **PASS** |

---

## 3. Сводка выполнения контрактного тестового набора

- **Общее число тестов**: 70
  - Базовые контрактные тесты Stage 4.2.8: 40
  - Негативные контрактные тесты Revision 1 (NG-01..NG-10): 10
  - Негативные контрактные тесты Revision 2 (G2-01..G2-10): 10
  - Негативные контрактные тесты Revision 3 (G3-01..G3-10): 10
- **Пройдено**: **70 / 70 PASS (100%)**
- **Ошибок**: **0**
- **Провалов**: **0**
- **Время выполнения**: 9.258 с
- **Окружение**: `<PRODUCTION_DIR>/python.exe` (Python 3.12, Windows 10 x64, Acer Aspire)

---

## 4. Честная фиксация недоказанных предпосылок

В соответствии с правилами правдивой метрики, система явно фиксирует следующие ограничения:

1. **`CONTRACT_GATE_READY: GO`**: Предохранительный гейт полностью закрыт и протестирован на 70 контрактных тестах.
2. **`REAL_CORPUS_PILOT: NOT_EXECUTED`**: К боевому корпусу не было сделано ни одного реального поискового запроса (`actual_search_calls = 0`).
3. **`SNAPSHOT_READY: NO_GO`**: Согласованный изолированный снимок боевой базы ещё не создан и не проверен. Боевая база данных `<PRODUCTION_DB_METADATA>` находится в состоянии READ-ONLY.
4. **`MODEL_INDEX_IDENTITY: UNVERIFIED`**: Сервер эмбеддингов на порту 8089 выключен; соответствие размерности индексов боевой модели не проверялось на реальных весах.
5. **`EMBEDDING_PROFILE: UNVERIFIED`**: Профиль совместимости модели с боевым индексом LanceDB не подтверждён живым прогоном.
6. **`PROCESS_LIFECYCLE_PLAN: PLAN_ONLY`**: Процедура безопасной остановки сервера проверена на контролируемых процессах, но боевой процесс `llama-server.exe` не запускался и не останавливался.
7. **`PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**: Боевой репозиторий `<PRODUCTION_DIR>/flying-rag-mcp` строго заблокирован на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`.
