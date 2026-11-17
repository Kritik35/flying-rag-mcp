# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — PILOT-SMOKE-011 (ТЗ `FR-TZ-20261117-011` / Редакция 1.1 от 17.11.2026, SHA-256 `fbe1f71f217320a7417fbbfab2f2c3fa878bf7f7f279eb1b9c353a7eb2bd19e3`, 22 657 байт)  
**Статус этапа**: **`PILOT_SMOKE: PASS` / `DATA_COPY: VERIFIED` / `STORAGE_SCOPE: ISOLATED_COPY_VERIFIED` / `EMBEDDING: HEALTHY` / `MODEL_INDEX_IDENTITY: VERIFIED_DISCRIMINATIVE` / `PRODUCTION_UNCHANGED: VERIFIED` / `PILOT_SEARCH_CALLS_ACTUAL: 6` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `BOOT_RECOVERY: CONFIGURED_UNOBSERVED` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенный коммит кода (Phase A code anchor)**: [`9b95161eaf8bfe7b512babc9dacc8d3c19cbc5d4`](https://github.com/Kritik35/flying-rag-mcp/commit/9b95161eaf8bfe7b512babc9dacc8d3c19cbc5d4) (Tree: `dce08a118d1ca1dac28c1082b3de9531bc5b2f20`)  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`5ff930929125d00da62b954fa40e7efcad82bd60`](https://github.com/Kritik35/flying-rag-mcp/commit/5ff930929125d00da62b954fa40e7efcad82bd60) (Tree: `61117a6df791d599cb9207ee2c28b0aa43262b6d`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый READ-ONLY)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `1794429401.7884293` — строго неизменна)  
**Реальные поисковые вызовы к изолированной копии**: **РОВНО 6** (`pilot_search_calls_actual = 6`, 3 пары EIG OFF vs EIG ON)  
**Режим**: STRICT OFFLINE / ISOLATED CORPUS IN TEMP / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги выполнения ТЗ-011 Редакции 1.1

Оператором в диалоге и в физическом ТЗ-011 Редакции 1.1 предоставлено прямое разрешение на три действия без повторных интерактивных запросов:
1. **Действие A (Копия базы данных)**: Создание независимой копии существующей базы в системном TEMP без symlink/junction.
2. **Действие B (Эмбеддинги)**: Проверка сервера `127.0.0.1:8089` (модель `Qwen3-Embedding-0.6B-Q8_0.gguf`, dim 1024, конечные float, семантическая дискриминативность).
3. **Действие C (Поисковый смоук-тест)**: Выполнение 6 реальных поисковых вызовов (3 пары EIG OFF/ON) по запросам Q004, Q010, Q088.

Все три действия полностью выполнены и верифицированы.

---

## 2. Сводка результатов по действиям A, B, C

### Действие A — Изолированная копия в системном TEMP (`DATA_COPY: VERIFIED`)
- Копия развёрнута в `C:\Users\almax\AppData\Local\Temp\flying_rag_isolated_pilot_corpus_FR011`.
- Скопированы `metadata.db` (1 485 103 104 байт, целостность `ok`), `lancedb` (203 файла, ~4.97 GiB), `table_parquet` (2 469 файлов, 54.97 МБ).
- Проверка `check_readonly_scope()`: возвращён статус **`ISOLATED_COPY_VERIFIED`**.
- Символические ссылки, hardlinks и junctions отсутствуют.

### Действие B — Проверка модели эмбеддингов (`EMBEDDING: HEALTHY`)
- Эндпоинт `http://127.0.0.1:8089/health`: `status: ok` (101 мс).
- Размерность векторов: 1024, значения конечные (NaN/Inf отсутствуют).
- Косинусная дискриминативность (`MODEL_INDEX_IDENTITY: VERIFIED_DISCRIMINATIVE`):
  - Связанная инженерная пара: `0.8756`.
  - Несвязанная пара: `0.2784`.

### Действие C — 6 реальных поисковых вызовов (`PILOT_SMOKE: PASS`)
- Выполнено ровно 6 вызовов (3 пары OFF/ON):
  1. `Q004` (`СП 7.13130 пункт 6.4`):
     - OFF / ON: Top hit `СП 7.13130.docx`, chunk `clause_6.4` (100% совпадение выдачи).
     - Теневой EIG: `CONGRUENT`, `USABLE_FOR_ANSWER`, `EXACT_BOUNDARIES`, `COMPLETE`.
  2. `Q010` (`СП 7.13130 пункт 6.10`):
     - OFF / ON: Top hit `СП 7.13130.docx`, chunk `clause_6.10` (100% совпадение выдачи).
     - Теневой EIG: `RETRIEVAL_WITHOUT_CERTIFIED_EVIDENCE`, `EVIDENCE_PARTIAL`, `TRUNCATED`.
  3. `Q088` (`СП 60.13330 пункт 7.1.1`):
     - OFF / ON: Top hit `СП 60.13330.2020...docx`, chunk `clause_7.1.1` (100% совпадение выдачи).
     - Теневой EIG: `SOURCE_AMBIGUOUS`, `AMBIGUOUS_EDITIONS`, `REFUSAL_REQUIRED`.
- Боевая база данных `C:\RAG_Acer\data_imported\metadata.db`: размер (1 485 103 104) и mtime (`1794429401.7884293`) не изменились, WAL отсутствует (`0 байт`). Мутаций боевого окружения: **СТРОГО 0** (`PRODUCTION_UNCHANGED: VERIFIED`).

---

## 3. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`PILOT_SMOKE`** | **`PASS`** | 6 поисковых вызовов выполнены успешно на изолированной копии. |
| **`DATA_COPY`** | **`VERIFIED`** | Физическая копия создана в системном TEMP, целостность SQLite подтверждена. |
| **`STORAGE_SCOPE`** | **`ISOLATED_COPY_VERIFIED`** | Проверка `check_readonly_scope()` подтвердила расположение в системном TEMP. |
| **`EMBEDDING`** | **`HEALTHY`** | Сервер 8089 стабилен, размерность 1024, NaN/Inf отсутствуют. |
| **`MODEL_INDEX_IDENTITY`** | **`VERIFIED_DISCRIMINATIVE`** | Косинусная близость: 0.8756 для релевантной пары vs 0.2784 для нерелевантной. |
| **`PILOT_SEARCH_CALLS_ACTUAL`** | **`6`** | Выполнено ровно 6 вызовов (3 пары). Лишних обращений 0. |
| **`PRODUCTION_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата таблиц LanceDB отложено. |
| **`BOOT_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Задача в Task Scheduler настроена на вход пользователя и 5-минутный интервал. |
| **`DETECTION_DELIVERY`** | **`OPERATIONAL`** | Монитор работает штатно, ТЗ-011 успешно обнаружено и обработано. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остаётся строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 4. Детальные отчёты этапа

- [PILOT_ENTRY_VERIFICATION_012.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_ENTRY_VERIFICATION_012.md) / [pilot_entry_verification_012.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_entry_verification_012.json) — Анализ замечаний аудитора и проверка 12 условий P6-01..P6-12 допуска к пилоту (ТЗ-012 Редакция 1.0).
- [PILOT_SMOKE_011_REV1_1.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_SMOKE_011_REV1_1.md) / [pilot_smoke_011_rev1_1.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_smoke_011_rev1_1.json) — Отчёт о выполнении поискового пилота: создание изолированной копии, проверка модели и 6 реальных поисковых вызовов (ТЗ-011 Редакция 1.1).
- [WATCHER_BOOT_RECOVERY_011.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/WATCHER_BOOT_RECOVERY_011.md) / [watcher_boot_recovery_011.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/watcher_boot_recovery_011.json) — Восстановление монитора Drive после ребута.
- [PILOT_ENTRY_011.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/PILOT_ENTRY_011.md) / [pilot_entry_011.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/pilot_entry_011.json) — Подготовка поискового пилота (ТЗ-011 Редакция 1.0).
