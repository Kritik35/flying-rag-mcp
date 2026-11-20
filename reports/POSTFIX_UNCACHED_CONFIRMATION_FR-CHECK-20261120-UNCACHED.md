# FlyingRAG — Отчёт о контрольном пилоте с обходом кэша (FR-CHECK-20261120-UNCACHED)

**Дата:** 20 ноября 2026 года  
**Санкция:** `FR-AUTH-20261120-UNCACHED-SIX-CALLS` (одноразовое разрешение оператора от 20.11.2026)  
**Идентификатор запуска:** `FR-CHECK-20261120-UNCACHED`  
**Уникальный run ID:** `1795155809_d15a7c7c`  
**Целевая ветка:** `audit/stage4-2-verification`  
**Итоговый статус:** **`HALTED_AFTER_FAILURE_CALL_1: CACHE_BYPASS_NOT_CONFIRMED`**  
**Статус одноразовой санкции:** **ИСПОЛЬЗОВАНА (CONSUMED) — повторные запуски запрещены**  
**Реальные попытки / child launches:** **1**  
**Успешные вызовы:** **0**  
**Оставшиеся запланированные вызовы (2..6):** **НЕ ЗАПУСКАЛИСЬ (STOP ON FIRST ERROR)**  
**Состояние боевой БД (1 485 103 104 байт, WAL: 0):** **НЕИЗМЕННА (VERIFIED)**  
**watcher.pause:** **АКТИВЕН**

---

## 1. Предусловия и подготовка

1. **Интеграция PR № 4**:
   - Ветка: `audit/one-shot-uncached-output-guard` (PR #4, https://github.com/Kritik35/flying-rag-mcp/pull/4).
   - Коммит: [`e075f918a41abed6bc87ee9566e22eb310d0326a`](https://github.com/Kritik35/flying-rag-mcp/commit/e075f918a41abed6bc87ee9566e22eb310d0326a).
   - CI: `focused-tests` — **SUCCESS** (2/2).
   - Интеграция: Fast-forward в `audit/stage4-2-verification` без `amend` и без `force push`.
   - Защита выходного файла: добавлен аргумент `--report-id`, исключительное создание (`open(..., 'x')`), запрет перезаписи исторических отчётов.
2. **Офлайн-верификация**:
   - Новые тесты `tests.test_uncached_report_output_guard`: **5/5 PASS**.
   - Регрессионный пакет ТЗ-014 – ТЗ-017 (93 теста): **93/93 PASS**.
   - Компиляция `py_compile`: без ошибок.
   - Проверка имени отчёта: файл `reports/postfix_uncached_confirmation_FR-CHECK-20261120-UNCACHED.json` до старта отсутствовал.
3. **Read-only preflight (`--dry-run --no-cache`)**:
   - `checks_passed`: `true`.
   - `storage_scope`: `ISOLATED_COPY_VERIFIED`.
   - `model_service`: `HEALTHY` (PID 2404, 127.0.0.1:8089).
   - `production_invariants`: `PRODUCTION_METADATA_UNCHANGED: VERIFIED`.
   - Поисковых вызовов в preflight: строго 0.

---

## 2. Ход выполнения контрольного запуска (Live Run)

Команда запуска:
```powershell
python tests/postfix_pilot_harness_015.py --execute-approved-pilot --no-cache --report-id FR-CHECK-20261120-UNCACHED
```

### Вызов 1: [Q004] «СП 7.13130 пункт 6.4» (EIG OFF)
* **Параметры:** `no_cache = True`, `shadow_mode = OFF`, `timeout_sec = 60.0`.
* **Дочерний воркер:** запущен с аргументами `--query "СП 7.13130 пункт 6.4" --shadow-mode 0 --no-cache ...`.
* **Фактический результат:**
  * Дочерний процесс выполнял реальный «холодный» поиск по некэшированному 5.33 ГБ LanceDB индексу и 1.48 ГБ SQLite базе изолированного стенда FR011.
  * Время выполнения превысило установленный таймаут `timeout_sec = 60.0` с.
  * На отметке **60.091 с** (`elapsed_ms: 60091.13`) сработал защитный таймаут `subprocess.TimeoutExpired`.
  * Дочерний процесс был принудительно и чисто завершён (`proc.terminate()`), остаточных процессов не зафиксировано.
  * Ввиду превышения таймаута воркер не успел вернуть JSON со статусом `cache_disabled: True`.
  * Harness применил строгое правило fail-closed:  
    `call_info["success"] = False`  
    `call_info["error"] = "CACHE_BYPASS_NOT_CONFIRMED"`.

### Срабатывание правила немедленной остановки (Fail-Fast)
* Согласно санкции `FR-AUTH-20261120-UNCACHED-SIX-CALLS` (п. 21, 31, 53): при первой же ошибке, таймауте или неподтверждении обхода кэша серия немедленно останавливается.
* Попытки 2..6 (Q004 EIG ON, Q010 OFF/ON, Q088 OFF/ON) **НЕ ЗАПУСКАЛИСЬ**.
* Повторные попытки вызова 1 **НЕ ПРОВОДИЛИСЬ**.
* Итоговый статус серии: **`HALTED_AFTER_FAILURE_CALL_1: CACHE_BYPASS_NOT_CONFIRMED`**.

---

## 3. Фиксация артефактов и безопасность

1. **Санированный отчёт JSON**:
   * Создан в режиме exclusive create:  
     `reports/postfix_uncached_confirmation_FR-CHECK-20261120-UNCACHED.json`.
   * Исторические файлы `postfix_pilot_results_015.json` и `postfix_real_diagnostic_016.json` сохранены без изменений.
2. **Приватный raw-файл результатов**:
   * Сохранён в системном TEMP:  
     `<PRIVATE_RAW_TEMP>/postfix_pilot_raw_results_FR-CHECK-20261120-UNCACHED_1795155809_d15a7c7c.json`.
   * SHA-256: `eea7086b93a1fd1dd8c092b39280eddc78b9754361f38c5892bd687293651bdc`.
3. **Неизменность production окружения**:
   * `<PRODUCTION_DB_METADATA>`: 1 485 103 104 байт, LastWriteTime: 11.11.2026 23:36:41.
   * `metadata.db-wal`: 0 байт.
   * `watcher.pause`: активен (`True`).
   * **Мутаций production: 0 байт.**

---

## 4. Инженерный диагноз и выводы

1. **Причина остановки**:
   * Таймаут единичного вызова в `execute_bounded_search()` зафиксирован на уровне 60.0 с.
   * В ТЗ-016 все 6 вызовов завершались за ~50 мс исключительно из-за воспроизведения исторических записей из `search_cache`.
   * При реальном обходе кэша (`use_cache=False`) прямой векторный поиск LanceDB по 5.33 ГБ хранилищу (203 файла / 2469 паркетов) совместно с FTS SQLite на мобильном CPU ноутбука Acer в холодном состоянии превышает 60 секунд.
2. **Соблюдение регламента**:
   * Одноразовое разрешение оператора `FR-AUTH-20261120-UNCACHED-SIX-CALLS` полностью исчерпано (попытка совершена).
   * Автоматический повтор или увеличение таймаута без явного согласования оператора запрещены.
   * Проект остановлен в безопасном состоянии.
