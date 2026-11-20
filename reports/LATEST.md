# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.11 / FR-CHECK-20261120-STAGETRACE — КОНТРОЛЬНЫЙ ПИЛОТ С ТЕЛЕМЕТРИЕЙ ЭТАПОВ И ОБХОДОМ КЭША  
**Основание (санкция оператора)**: `FR-AUTH-20261120-STAGE-TRACE-CONTROLLED-PILOT.txt` от 20.11.2026 (7 652 байт)  
**Идентификатор запуска**: `FR-CHECK-20261120-STAGETRACE`  
**Уникальный идентификатор серии (Run ID)**: `1795164253_21580739`  
**Статус этапа**: **`ONE_SHOT_PILOT: PILOT_COMPLETED_SUCCESSFULLY` / `ALL_6_CALLS_PASS (3/3 PAIRS)` / `CACHE_BYPASS: CONFIRMED (6/6)` / `STAGE_TELEMETRY: VERIFIED` / `OPERATOR_SANCTION: CONSUMED` / `ATTEMPTED_CALLS: 6` / `COMPLETED_CALLS: 6` / `PR6_INTEGRATED: YES` / `STAGE_TIMING_TESTS: 20/20 PASS` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `WATCHER_PAUSE: ACTIVE` / `RETRY_ATTEMPTS: 0 (STRICTLY PROHIBITED)`**  
**Интегрированный коммит PR № 6**: [`98ec4cc97ff1995a7faa6ba9703d6c2c81f011d4`](https://github.com/Kritik35/flying-rag-mcp/commit/98ec4cc97ff1995a7faa6ba9703d6c2c81f011d4)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `11.11.2026 23:36:41` — строго неизменна)  
**Режим**: ONE-SHOT AUDITED DIAGNOSTIC PILOT / FAIL-FAST ON FIRST ERROR / NO RETRY / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги контрольного запуска с телеметрией этапов и обходом кэша

1. **Интеграция PR № 6 и инструментальная телеметрия**:
   * В ветку `audit/stage4-2-verification` интегрирован PR #6 (`audit/timeout-stage-diagnostics`), добавивший модуль `stage_timing.py`.
   * Обеспечена безопасная фиксация меток времени этапов поиска без раскрытия конфиденциальных данных и текстов документов в `stderr`.
   * Сохранена первопричина ошибок при превышении лимита времени (`EXECUTION_TIMEOUT_EXPIRED`).

2. **Ход выполнения контрольной серии (FR-CHECK-20261120-STAGETRACE)**:
   * Команда запуска:
     ```powershell
     python tests/postfix_pilot_harness_015.py --execute-approved-pilot --no-cache --report-id FR-CHECK-20261120-STAGETRACE
     ```
   * Все 6 поисковых вызовов успешно завершены в пределах лимита 60 с на воркер:
     - **Q004 (СП 7.13130 п. 6.4)**: EIG OFF = 44 492.8 мс, EIG ON = 40 802.9 мс. `pair_verdict = PASS`.
     - **Q010 (СП 7.13130 п. 6.10)**: EIG OFF = 55 118.8 мс, EIG ON = 52 035.0 мс. `pair_verdict = PASS`.
     - **Q088-2020 (СП 60.13330.2020 п. 7.1.1)**: EIG OFF = 55 570.4 мс, EIG ON = 56 246.7 мс. `pair_verdict = PASS`.
   * Подтверждение обхода кэша (`cache_disabled: True`) получено по всем 6 вызовам (`cache_bypass_status: CONFIRMED`).

3. **Результаты телеметрии этапов (Stage Trace)**:
   * Импорт модулей Python: 2.9 – 8.5 с.
   * ENR (нормативное разрешение): 3.5 – 12.3 с.
   * Генерация эмбеддингов через `llama-server`: 7.4 – 12.9 с.
   * Гибридный векторно-текстовый поиск (LanceDB ANN + FTS + Rerank): 15.4 – 19.8 с.
   * Извлечение нормативных пунктов: 1.4 – 2.6 с.
   * Асинхронный Observer (EIG ON): 50 – 70 мс.
   * Диапазон общего времени поиска без кэша: **40.8 – 56.3 с**.

4. **Механическая эквивалентность и доказательная база**:
   * Для всех 3 пар подтверждена полная идентичность ранжирования (`rank_identical = True`) и нормализованного содержимого (`normalized_payload_identical = True`).
   * Строго разграничены физические parent/child чанки и синтетические derived clause labels.
   * Статус `SOURCE_FIDELITY` сохранён как `UNKNOWN` до валидации по независимому эталону.

5. **Неприкосновенность боевой среды**:
   * Производственная база `metadata.db` (1 485 103 104 байт, WAL = 0) строго неизменна.
   * Блокиратор автоматизации `watcher.pause` активен (`True`).
   * Хеш приватного файла сырых результатов (`Temp`): `a8521859625102bbf44daf405d570b77ef5d2adf5fb93c37fa353b77d84ed873`.


---

## 2. Сводная таблица статусов

| Параметр | Значение | Обоснование |
|:---|:---:|:---|
| **`STATUS`** | **`PILOT_COMPLETED_SUCCESSFULLY`** | Все 6 поисковых вызовов успешно завершены в пределах 60 с лимита. |
| **`PR6_INTEGRATED`** | **`YES`** | PR #6 объединён в `audit/stage4-2-verification` (коммит `98ec4cc`). |
| **`STAGE_TELEMETRY`** | **`VERIFIED`** | Зафиксировано 46–48 очищенных меток этапов на каждый вызов. |
| **`CACHE_BYPASS_STATUS`** | **`CONFIRMED (6/6)`** | Каждый воркер вернул явное подтверждение `cache_disabled: True`. |
| **`MECHANICAL_PAIR_AGREEMENT`** | **`PASS (3/3)`** | Ранжирование и полезная нагрузка строго идентичны между EIG OFF и ON. |
| **`ATTEMPTED_CALLS`** | **`6`** | Все 6 запланированных вызовов запущены. |
| **`COMPLETED_CALLS`** | **`6`** | 0 таймаутов, 0 сбоев JSON, 0 ошибок. |
| **`RETRY_POLICY`** | **`ZERO_RETRIES`** | Никаких повторных запусков (0 retries). |
| **`SANCTION_STATUS`** | **`CONSUMED`** | Разрешение FR-AUTH-20261120-STAGE-TRACE полностью израсходовано. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` активен (`True`). |

---

## 3. Детальные отчёты этапа

- [POSTFIX_UNCACHED_CONFIRMATION_FR-CHECK-20261120-STAGETRACE.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POSTFIX_UNCACHED_CONFIRMATION_FR-CHECK-20261120-STAGETRACE.md) — детальный аналитический отчёт с телеметрией этапов.
- [postfix_uncached_confirmation_FR-CHECK-20261120-STAGETRACE.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/postfix_uncached_confirmation_FR-CHECK-20261120-STAGETRACE.json) — структурированные санированные результаты пилота.
- [POSTFIX_UNCACHED_CONFIRMATION_FR-CHECK-20261120-UNCACHED.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POSTFIX_UNCACHED_CONFIRMATION_FR-CHECK-20261120-UNCACHED.md) — отчёт предыдущей попытки с таймаутом.
- [POST_PILOT_NORMATIVE_CLAUSE_RECONSTRUCTION_017.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POST_PILOT_NORMATIVE_CLAUSE_RECONSTRUCTION_017.md) — отчёт ТЗ-017.
