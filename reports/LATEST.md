# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.11 / FR-TZ-20261120-019 Rev 1.2 — ПОЛНАЯ САНИТИЗАЦИЯ ОТЧЁТОВ И FAIL-CLOSED СКАНЕР ПУБЛИКАЦИЙ  
**Основание**: `FR-TZ-20261120-019_OFFLINE_Q010_EVIDENCE_GATE_98ec4cc_430d63fc.txt` (10 999 байт, SHA-256: `7bab0e1d67af58df6dfd052b598ac334e274579ab27713ae910703f867b07e4d`)  
**Идентификатор исходного пилота**: `FR-CHECK-20261120-STAGETRACE` (Run ID: `1795164253_21580739`)  
**Статус этапа**: **`TZ019_OFFLINE_FORENSICS: COMPLETED` / `PR7_INTEGRATED: YES (0d92ff31)` / `PR8_INTEGRATED: YES (a6ccb90)` / `Q010_EXACT_CLAUSE_VISIBILITY: IMPLEMENTED` / `CACHE_ROTATION_V12: VERIFIED` / `ALL_109_REPORTS_CLEAN: 0_LEAKS_VERIFIED` / `FAIL_CLOSED_PUBLICATION_SCANNER: ENFORCED (15/15 PASS)` / `CI_FOCUSED_TESTS: PASS` / `PY_COMPILE: PASS` / `NEW_SEARCH_CALLS: STRICTLY 0 (SANCTION CONSUMED)` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `WATCHER_PAUSE: ACTIVE`**  
**Базовый коммит публикации**: [`42c0f397db53c08ba2bf240838bd5ec1223c146e`](https://github.com/Kritik35/flying-rag-mcp/commit/42c0f397db53c08ba2bf240838bd5ec1223c146e)  
**Боевая база данных**: `<PRODUCTION_DB_METADATA>` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `11.11.2026 23:36:41` — строго неизменна)  
**Режим**: STRICTLY READ-ONLY OFFLINE AUDIT / ZERO SEARCH CALLS / PRODUCTION INVARIANTS ENFORCED / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Ключевые результаты и этапы реализации

1. **Форензический анализ сырых результатов (RAW) по ТЗ-019**:
   * Файл сырых результатов пилота: `<PRIVATE_RAW_TEMP>/postfix_pilot_raw_results_FR-CHECK-20261120-STAGETRACE_1795164253_21580739.json` (153 641 байт).
   * Вычисленный SHA-256: `a8521859625102bbf44daf405d570b77ef5d2adf5fb93c37fa353b77d84ed873` (байт-в-байт совпадает со значением в публичном отчёте).
   * Анализ выдачи по запросу Q010 («СП 7.13130 пункт 6.10», Call 3 EIG OFF и Call 4 EIG ON):
     - Ранг 1: `973d9901_c_0007` (parent `p_0000`, титульный лист СП 7, score 1.0)
     - Ранг 2: `973d9901_c_0008` (parent `p_0001`, приказ/введение СП 7, score 0.945)
     - Ранг 3: `403d97c3_c_0121` (parent `p_0015`, цитата из СП 514, score 1.0)
     - Ранг 4: `dc90ccd8_c_0607` (parent `p_0075`, Приказ 116, Приложение Д, score 1.0)
     - Ранг 5: `403d97c3_c_0116` (parent `p_0014`, цитата из СП 514, score 1.0)
   * **Факт**: `clause_6.10` **полностью отсутствует** на позициях 1–5 в обоих вызовах.

2. **Доказанная причинно-следственная цепочка вытеснения пункта 6.10**:
   * `NormRegistry.extract_clause_from_doc()` сшил пункт 6.10 (3 758 символов из parent-чанков `p_0021 + p_0022`), однако присвоил ему статус `context_partial`.
   * В `rag_server/tools.py` элементы с `context_partial` получают скор `0.85` (в отличие от `1.0` при `context_sufficient`) и вставляются в общий список по скору, а не на позицию 0.
   * Титульный чанк `973d9901_c_0007` получил лексический бонус по имени файла и достиг скора `1.0`.
   * Фильтр концентрации источников `concentrate_sources(quality_pool, max_docs=3)` в `storage/source_focus.py` отобрал топ-3 документа со скором `1.0`, полностью исключив синтетический элемент `"norm_clause"` (скор 0.85).

3. **Интеграция PR #7 (оценка доказательств)**:
   * PR #7 (`audit/evidence-gate-fix`) объединён коммитом [`0d92ff31`](https://github.com/Kritik35/flying-rag-mcp/commit/0d92ff31887be474dce409ad920fbc1efd20b9ab).
   * Устранена системная ошибка оценщика в `tests/postfix_pilot_harness_015.py`: титульный лист больше не признаётся полным пунктом (`FULL_CLAUSE_EVIDENCE = PASS`).
   * Введено строгое требование `verified_clause_context`. Регрессионные тесты `tests.test_evidence_fail_closed_018` (7/7) проходят успешно.

4. **Интеграция PR #8 (ранжирование и видимость точного нормативного пункта)**:
   * PR #8 (`audit/q010-explicit-clause-visibility`) объединён коммитом [`a6ccb90`](https://github.com/Kritik35/flying-rag-mcp/commit/a6ccb90).
   * Реализован модуль `rag_server/exact_clause_priority.py` с функцией `preserve_requested_clause()`.
   * Если фильтр концентрации источников исключил запрашиваемый нормативный пункт, `preserve_requested_clause()` сохраняет его в итоговой выдаче `final` на ранге 1, сохраняя честные признаки: `score = 0.85`, `context_partial`, `evidence_status = "EVIDENCE_PARTIAL"`, `structural_end_verified = False`, `rank_policy = "explicit_target_clause_identity"`, `evidence_warning = "PARTIAL_CLAUSE_STRUCTURAL_END_UNVERIFIED"`.
   * Полный, структурно подтверждённый результат того же пункта сохраняет безусловный приоритет перед частичным.
   * Версия ключа кэша обновлена до v12 (`retrieval-quality-v12-exact-clause-visibility`), что исключает воспроизведение старой титульной выдачи из постоянного кэша.
   * Новые тесты `tests.test_exact_clause_visibility_018`: **7/7 PASS**.
   * Исторические тесты `tests.test_retrieval_clause_edition_014` и `tests.test_retrieval_cache_revision_017`: **45/45 PASS**.

5. **Усиление защиты путей и приватности (B3, C19-06)**:
   * Исправлен порядок проверки путей: проверка принадлежности изолированному стенду (`isolated_pilot_corpus`, `isolated_config.yaml`) теперь выполняется **до** проверки `metadata.db`. Путь к изолированной SQLite корректно обозначается как `<ISOLATED_TEMP_CORPUS>/metadata.db`, а не `<PRODUCTION_DB_METADATA>`.
   * Добавлена функция `sanitize_report_text()`, маскирующая пути Windows внутри произвольных сообщений, логов, строк и Markdown-текстов.
   * Из публичных Markdown-отчётов исключены абсолютные локальные пути хоста к production-базе.
   * Автономные тесты `tests.test_report_path_sanitizer_019`: **9/9 PASS** (0.006 с).

6. **Неприкосновенность боевой среды**:
   * Производственная база `metadata.db` (1 485 103 104 байт, WAL = 0, mtime `11.11.2026 23:36:41`) строго неизменна.
   * Блокиратор автоматизации `watcher.pause` активен (`True`).
   * Новые поисковые вызовы: строго 0.

---

## 2. Сводная таблица статусов

| Параметр | Значение | Обоснование |
|:---|:---:|:---|
| **`STAGE`** | **`STAGE_4_2_11_PR8`** | Завершена оффлайн-приёмка и интеграция PR #8. |
| **`PR7_STATUS`** | **`INTEGRATED (0d92ff31)`** | Оценка полноты (fail-closed) влита в `audit/stage4-2-verification`. |
| **`PR8_STATUS`** | **`INTEGRATED (a6ccb90)`** | Видимость нормативного пункта влита в `audit/stage4-2-verification`. |
| **`CACHE_REVISION`** | **`v12`** | Ключ кэша обновлён (`retrieval-quality-v12-exact-clause-visibility`). |
| **`Q010_ROOT_CAUSE`** | **`PROVEN`** | Скор 0.85 (`context_partial`) + вытеснение фильтром `concentrate_sources(max_docs=3)`. |
| **`Q010_FIX_POLICY`** | **`PIN_PRESERVED`** | `preserve_requested_clause()` сохраняет пункт 6.10 с честным provenance. |
| **`PATH_SANITIZATION`** | **`ENHANCED (9/9 PASS)`** | `sanitize_report_text()` + приоритет isolated перед production. |
| **`SEARCH_CALLS`** | **`0`** | Новые вызовы не производились, санкция исчерпана. |
| **`PRODUCTION_DB`** | **`UNCHANGED`** | Размер 1 485 103 104 байт, WAL 0 байт, mtime 11.11.2026 23:36:41. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Маркер `watcher.pause` активен (`True`). |

---

## 3. Отчёты и ссылки этапа

- [OFFLINE_Q010_EVIDENCE_GATE_019.md](./OFFLINE_Q010_EVIDENCE_GATE_019.md) — аналитический отчёт форензики ТЗ-019.
- [offline_q010_evidence_gate_019.json](./offline_q010_evidence_gate_019.json) — структурированные результаты форензики ТЗ-019.
- [POSTFIX_UNCACHED_CONFIRMATION_FR-CHECK-20261120-STAGETRACE.md](./POSTFIX_UNCACHED_CONFIRMATION_FR-CHECK-20261120-STAGETRACE.md) — аналитический отчёт исходного контрольного пилота.
