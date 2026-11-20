# FlyingRAG — Форензика результатов Q010 и защита путей (ТЗ-019 Rev 1.1)

**Дата проведения:** 20 ноября 2026 года  
**Станция:** Acer TravelMate P215-52 (Windows 11)  
**Репозиторий:** `Kritik35/flying-rag-mcp`  
**Целевая ветка:** `audit/stage4-2-verification`  
**Основание (ТЗ оператора):** `FR-TZ-20261120-019_OFFLINE_Q010_EVIDENCE_GATE_98ec4cc_430d63fc.txt` (10 999 байт, SHA-256: `7bab0e1d67af58df6dfd052b598ac334e274579ab27713ae910703f867b07e4d`)  
**Статус осмотра приватного RAW:** **`ПРЯМОЙ WINDOWS RAW ОСМОТРЕН ИСПОЛНИТЕЛЕМ НА ACER`**  
**Приватный RAW-файл:** `<PRIVATE_RAW_TEMP>/postfix_pilot_raw_results_FR-CHECK-20261120-STAGETRACE_1795164253_21580739.json` (153 641 байт, SHA-256: `a8521859625102bbf44daf405d570b77ef5d2adf5fb93c37fa353b77d84ed873`)  
**Новые поисковые вызовы:** **0 (СТРОГО ЗАПРЕЩЕНЫ, САНКЦИЯ ИЗРАСХОДОВАНА)**  
**Состояние production БД (`metadata.db`, 1 485 103 104 байт, WAL: 0):** **`СТРОГО НЕИЗМЕННА (VERIFIED)`**  
**Блокиратор автоматизации (`watcher.pause`):** **`АКТИВЕН (True)`**

---

## 1. Цепочка коммитов и верификация PR № 7

1. **Исходный код реального пилота:** коммит [`98ec4cc`](https://github.com/Kritik35/flying-rag-mcp/commit/98ec4cc97ff1995a7faa6ba9703d6c2c81f011d4) (tree `8e5a627a80356103ca996d0d934f28d674a4b344`).
2. **Публикация отчёта пилота:** коммит [`430d63fc`](https://github.com/Kritik35/flying-rag-mcp/commit/430d63fca49ca59cf63b27c745cb5c0b57fcc813) (parent `98ec4cc`, tree `510c1c343e3ae31726804431ac276db11b1a8485`).
3. **Интегрированный коммит PR № 7:** [`0d92ff31`](https://github.com/Kritik35/flying-rag-mcp/commit/0d92ff31887be474dce409ad920fbc1efd20b9ab) (parents `430d63fc` и `de415fc`, tree `8a4ef6a666235723df78e5f62bd77600f663dd73`).
4. **Статус PR № 7:**
   * CI Windows в GitHub Actions: **SUCCESS** (run 44708817273).
   * Офлайн-тесты `tests.test_evidence_fail_closed_018`: **7/7 PASS** (0.002 с).
   * Кодовая ошибка `FULL_CLAUSE_EVIDENCE=PASS` при неизвестном пункте устранена (для титульного чанка Q010 оценщик возвращает `UNKNOWN`). Исправления не дублируются.

---

## 2. Форензика результатов Q010 (СП 7.13130 пункт 6.10) из приватного RAW

Прямой осмотр RAW-файла подтвердил побайтовое совпадение хеша `a8521859625102bbf44daf405d570b77ef5d2adf5fb93c37fa353b77d84ed873`.

### 2.1. Позиции 1–5 для вызовов 3 (EIG OFF) и 4 (EIG ON)
Выдачи строго идентичны между EIG OFF и ON:

| Ранг | `chunk_id` | `parent_id` | `doc_id` | Документ | Скор | Тип скора | Фактическое содержание |
| :-: | :--- | :--- | :--- | :--- | :-: | :---: | :--- |
| **1** | `973d9901_c_0007` | `973d9901_p_0000` | `973d9901` | СП 7.13130.docx | **1.0** | Вектор/FTS + Quality | Преамбула приказа МЧС РФ № 116 от 21.02.2013 |
| **2** | `973d9901_c_0008` | `973d9901_p_0001` | `973d9901` | СП 7.13130.docx | **0.945** | Вектор/FTS + Quality | Пункт 2 приказа МЧС № 116 |
| **3** | `403d97c3_c_0121` | `403d97c3_p_0015` | `403d97c3` | СП 514.1311500.2022 | **1.0** | Вектор/FTS + Quality | Временные здания (косвенная ссылка на СП 7.13130) |
| **4** | `dc90ccd8_c_0607` | `dc90ccd8_p_0075` | `dc90ccd8` | Приказ МЧС № 116 ред. 2025 | **1.0** | Вектор/FTS + Quality | Приложение Д (тоннели, ссылка на СП 7.13130) |
| **5** | `403d97c3_c_0116` | `403d97c3_p_0014` | `403d97c3` | СП 514.1311500.2022 | **1.0** | Вектор/FTS + Quality | Временные воздуховоды (ссылка на СП 7.13130) |

* **Попадал ли ENR `clause_6.10` в топ-5 выдачи?** **НЕТ, пункт 6.10 отсутствует в топ-5.**
* **Извлекался ли пункт 6.10 модулем NormRegistry?** **ДА.** Метод `norm_reg.extract_clause_from_doc()` находит пункт 6.10 со сшивкой `973d9901_p_0021 + 973d9901_p_0022` (`is_stitched: True`, длина 3 758 символов), но со статусом **`context_partial`**.

### 2.2. Причинно-следственная цепочка вытеснения пункта 6.10
`source line → candidate → ranking → wrong top hit`:
1. `rag_server/tools.py` (строка 696): пункт со статусом `context_partial` получает скор **`0.85`** (в отличие от `1.0` для `context_sufficient`).
2. `rag_server/tools.py` (строки 721–728): частичный пункт не вставляется безусловно на ранг 0, а помещается в пул по своему скору (`ins_idx`).
3. Чанк титульной страницы (`973d9901_c_0007`) за счёт лексических совпадений названия документа получает надбавку качества и скор **`1.0`**, опережая `clause_6.10`.
4. `storage/source_focus.py` (строки 68–75): фильтр `concentrate_sources(quality_pool, max_docs=3)` отбирает топ-3 документа по максимальному скору (`973d9901` [1.0], `403d97c3` [1.0], `dc90ccd8` [1.0]).
5. Синтетический элемент `clause_item` имеет `"doc_id": "norm_clause"` со скором `0.85`. Так как `0.85 < 1.0`, документ `"norm_clause"` **полностью исключается из отобранных документов**.
6. `fill_to_top_k` возвращает 5 чанков из оставшихся документов, в результате чего пункт 6.10 полностью отсутствует в итоговой выдаче, а на первое место попадает титульный лист.

---

## 3. Устранение публикации локальных абсолютных путей (C19-06, B3)

Для соблюдения запрета на публикацию пользовательских абсолютных путей в публичных отчётах реализован механизм маскирования:
1. **Реализация в `tests/postfix_pilot_harness_015.py`:**
   * Добавлена функция `sanitize_public_report_paths(report: dict) -> dict`, рекурсивно заменяющая Windows-пути на безопасные семантические токены:
     * `isolated_corpus_root` $\to$ `<ISOLATED_TEMP_CORPUS>`
     * `isolated_config_path` $\to$ `<ISOLATED_TEMP_CORPUS>/isolated_config.yaml`
     * `production_db_path` $\to$ `<PRODUCTION_DB_METADATA>`
     * `watcher_pause_path` $\to$ `<WATCHER_PAUSE_MARKER>`
     * `model_name` $\to$ `<MODEL_DIR>/Qwen3-Embedding-0.6B-Q8_0.gguf`
     * `raw_results_temp_path` $\to$ `<PRIVATE_RAW_TEMP>/postfix_pilot_raw_results_...json`
     * `source_path` $\to$ `<NTD_CORPUS>/СП 7.13130.docx`
   * Функция вызывается перед записью любого публичного отчёта JSON/MD.
2. **Синтетические офлайн-тесты (`tests/test_report_path_sanitizer_019.py`):**
   * Разработано 6 синтетических тестов:
     - `test_windows_paths_in_preflight_are_masked` — PASS
     - `test_raw_temp_path_is_masked` — PASS
     - `test_hit_paths_are_masked` — PASS
     - `test_non_path_strings_and_hashes_strictly_preserved` — PASS
     - `test_no_windows_drive_letter_survives_in_serialized_json` — PASS
     - `test_generic_windows_path_fallback` — PASS
   * Результат: **6/6 PASS** (0.004 с).
   * Тест включён в CI-пакет `.github/workflows/ci.yml`.

---

## 4. Экспертиза ветки `audit/q010-explicit-clause-visibility`

В ветке `origin/audit/q010-explicit-clause-visibility` оператором предложено архитектурное решение выявленного дефекта:
1. **Модуль `rag_server/exact_clause_priority.py` (`preserve_requested_clause`):**
   * Гарантирует сохранение явно запрошенного нормативного пункта при наличии физической привязки, не позволяя фильтру концентрации отсечь его.
   * Для частичного пункта сохраняет скор `0.85`, пометку `EVIDENCE_PARTIAL` и `structural_end_verified=False`.
   * Выставляет `rank_policy="explicit_target_clause_identity"` и предупреждение `PARTIAL_CLAUSE_STRUCTURAL_END_UNVERIFIED`.
   * Не вытесняет уже подтверждённый полный пункт.
2. **Ротация ключа кэша:**
   * Ключ обновлён на `retrieval-quality-v12-exact-clause-visibility`, исключая воспроизведение старых некорректных ответов из `search_cache`.
3. **Локальная проверка тестов ветки:**
   * Все 52 теста ветки успешно пройдены: **52/52 PASS** (64.4 с).

---

## 5. Производственные инварианты и статус безопасности

* **Production SQLite DB (`<PRODUCTION_DB_METADATA>`):** 1 485 103 104 байт, LastWriteTime: `11.11.2026 23:36:41` (строго без изменений).
* **WAL-файл:** 0 байт.
* **Блокиратор автоматизации (`watcher.pause`):** активен (`True`).
* **Поисковые вызовы:** строго 0.
* **Статус доказательств:**
  * `Q010 TARGET_CLAUSE_MATCH`: **`UNKNOWN`** (для ранее опубликованного отчёта).
  * `SOURCE_FIDELITY`: **`UNKNOWN`** (для всех запросов).
  * `CONSISTENT_SNAPSHOT` и `MODEL_INDEX_IDENTITY`: **`UNVERIFIED`**.
  * 3/3 механических EIG PASS не повышаются до нормативных ответов.
