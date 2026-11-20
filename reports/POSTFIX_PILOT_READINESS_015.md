# Отчёт о готовности к пост-фикс пилоту: ТЗ-015 Rev 1.3 (Stage 4.2.9 / LIMITED REAL-PAYLOAD EVIDENCE CONTRACT ERRATA)

**Документ**: Отчёт об адаптации оценщика нормативных доказательств к реальным полям MCP-выдачи FlyingRAG, строгой проверке полноты и источника, изоляции механической и качественной телеметрии, верификации тестовой матрицы E15-01..08 и исправлении идентификационного SHA-256 (Rev 1.4 Provenance Errata)  
**Техническое задание**: [FR-TZ-20261118-015_REV1_3_REAL_PAYLOAD_EVIDENCE_04fe8d22_3947226e.txt](<FILE_URI_REDACTED>)  
**Редакция**: Редакция 1.3 от 18 ноября 2026 года | Размер: 17 458 байт, UTF-8 | SHA-256: `010412b209b22b399f1c1ea64b06fb2e3dfa98d7974a65f63462ee2db7a8994f`  
**Errata идентификации**: [FR-TZ-20261118-015_REV1_4_PROVENANCE_INTEGRITY_821cbe05_794199bf.txt](<FILE_URI_REDACTED>) (12 630 байт, UTF-8, SHA-256: `fe3c4a3d1e2f0639af42143ac0470c28819f278567042d6f8e6693760e0f4bc1`)  
**Ветка аудита**: `audit/stage4-2-verification`  
**Коммит проверенного кода (Phase A Rev 1.3)**: [`821cbe05708c8ba627e60a35ec77cd57e8550574`](https://github.com/Kritik35/flying-rag-mcp/commit/821cbe05708c8ba627e60a35ec77cd57e8550574)  
**Родительский коммит отчётов**: [`794199bf0702b1d8f7dd15511251eaca209a5a2c`](https://github.com/Kritik35/flying-rag-mcp/commit/794199bf0702b1d8f7dd15511251eaca209a5a2c)  
**Официальный вердикт**: **`WAITING_OPERATOR_SEARCH_APPROVAL` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `REPORT_PROVENANCE_GATE: GO` / `HARNESS_REAL_PAYLOAD_CONTRACT: GO` / `HARNESS_FAIL_CLOSED_VERIFIED: YES` / `TEST_SUITE_E15: 8/8 PASS` / `TEST_SUITE_G15_R12: 10/10 PASS` / `TEST_SUITE_P15: 10/10 PASS` / `REGRESSION_014: 42/42 PASS` / `TOTAL_SUITE_PASS: 70/70 PASS` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PILOT_NATURE: DIAGNOSTIC_PILOT_ONLY` / `PRODUCTION_CERTIFICATION: BLOCKED_UNVERIFIED_PREREQUISITES` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**

---

## 1. Устранение замечаний ТЗ-015 Rev 1.3 и Rev 1.4 (P0-E1 .. P0-PROV)

### 1.1. P0-E1: Совместимость с реальными полями MCP-выдачи FlyingRAG
- **Проблема**: В Rev 1.2 функция `evaluate_normative_evidence()` ожидала синтетические поля `norm`, `doc_name`, `clause_num`, `edition`. В рабочем коде FlyingRAG (`vector_store.py`, `tools.py`) возвращаются реальные поля:
  - `file_name` (например, `SP_7_13130_2013_izm1_2.pdf`), `source_path`
  - `section` (например, `Пункт 6.10`), `derived_label` (например, `clause_6.10`)
  - `parent_ids` (список строк, напр. `["parent_0021", "parent_0022"]`), `parent_id`, `chunk_id`
  - `clause_status` (`complete` / `context_partial`), `evidence_status` (`EVIDENCE_FULL` / `EVIDENCE_PARTIAL`)
- **Решение**:
  - `evaluate_normative_evidence()` извлекает атрибуты как из реальных нативных полей MCP, так и из легаси-синтетических фикстур.
  - **`TARGET_DOC_MATCH`**: Номер СП извлекается из `file_name`, `source_path`, `norm`, `doc_name`. Проверяется точное совпадение номера (СП 7 vs СП 60). Документ с чужим номером получает `FAIL`. Отсутствие информации о документе возвращает `UNKNOWN`. Указатель `doc_id='norm_clause'` отвергается как псевдо-идентификатор. Фиксируется происхождение: `SOURCE_METADATA` или `FILENAME_INFERRED`.
  - **`TARGET_EDITION_MATCH` (Q088-2020)**: Редакция 2020 года принимается при наличии `2020` в имени файла (`FILENAME_INFERRED`) либо в метаданных документа (`SOURCE_METADATA`). Наличие `2012` возвращает `FAIL`. Упоминание «2020» только в тексте чанка без подтверждения файла/метаданных возвращает `UNKNOWN` (при явном несоответствии файла — `FAIL`), но никогда не `PASS`.
  - **`TARGET_CLAUSE_MATCH`**: Точное сопоставление номера пункта (`6.10` != `6.100`, `6.4` != `6.4.1`) из полей `section`, `derived_label`, `clause_num`. Случайные ссылки в тексте чужого контекста («см. п. 6.10») дают `UNKNOWN`, а не `PASS`.
  - **`PHYSICAL_PARENT_IDS` и `DERIVED_LABEL`**: Чётко разделены физические идентификаторы родителей (`parent_ids` / `parent_id` / `chunk_id`) и синтетические метки (`derived_label`). Критерий `HAS_PAGE_OR_VALID_LOCATOR` получает `PASS` только при наличии физической привязки.

### 1.2. P0-E2: Строгая полнота и точность источника (Source Fidelity)
- **`FULL_CLAUSE_EVIDENCE`**:
  - Если `evidence_status == "EVIDENCE_PARTIAL"` или `clause_status == "context_partial"` или в тексте зафиксировано `[обрезано]` / `TRUNCATED`, критерий немедленно получает `FAIL`, даже если текст не пуст и в нём нет многоточия `...`.
  - Для **Q010 (пункт 6.10 СП 7)**: нормативно обязательными являются как предел огнестойкости EI 60, так и устройства с пределом EI 15. Отсутствие фрагмента с EI 15 даёт `FULL_CLAUSE_EVIDENCE = FAIL`.
  - Выход границ за пределы пункта в раздел 7 («7. Противодымная защита») или пункт 6.11 даёт `PARSER_BOUNDARY_STATUS = FAIL`.
- **`SOURCE_FIDELITY`**:
  - Никогда не выставляется `PASS` автоматически лишь по совпадению номера документа и пункта.
  - При отсутствии независимого эталонного текста источника для посимвольного/потокенового сравнения статус строго равен **`UNKNOWN`**.
- **`QUALITY_VERIFIED`**:
  - Равен `True` **ТОЛЬКО** если все критерии имеют статус `PASS`: `TARGET_DOC_MATCH == PASS`, `TARGET_EDITION_MATCH == PASS`, `TARGET_CLAUSE_MATCH == PASS`, `HAS_PAGE_OR_VALID_LOCATOR == PASS`, `FULL_CLAUSE_EVIDENCE == PASS`, `SOURCE_FIDELITY == PASS`, `PARSER_BOUNDARY_STATUS in [PASS, NOT_APPLICABLE]`.
  - Если хотя бы один критерий равен `FAIL` или `UNKNOWN`, `QUALITY_VERIFIED` строго равен `False`.

### 1.3. P1-E3: Телеметрия и строгое разделение пилота
- **`actual_corpus_search_calls = 0`**: Реальные вызовы по корпусу строго заблокированы (счётчик строго равен 0).
- **Счётчик запущенных процессов**: `child_spawned_calls` инкрементируется исключительно при фактическом вызове `subprocess.run()`.
- **`search_dispatch_confirmed`**: Равен `"CONFIRMED"` только при подтверждённом запуске реального поиска; в подготовительном режиме строго `"NOT_EXECUTED"`.
- **`PILOT_QUALITY`**: Равен `"UNVERIFIED"` при `QUALITY_VERIFIED = False` или наличии `UNKNOWN` в критериях качества. Механическая консистентность пары при этом фиксируется независимо: `MECHANICAL_PAIR_OK = True`.

### 1.4. P0-PROVENANCE: Исправление SHA-256 исходного ТЗ-015 Rev 1.3 (ТЗ-015 Rev 1.4 / P15-PROV-01..08)
- **Проблема**: В отчётах коммита `794199bf` был указан ошибочный хеш ТЗ-015 Rev 1.3 (`010412b2...8583`).
- **Независимая проверка**: Фактический файл `FR-TZ-20261118-015_REV1_3_REAL_PAYLOAD_EVIDENCE_04fe8d22_3947226e.txt` в локальной синхронизации `<PATH_REDACTED>/Мой диск\FlyingRAG_TZ_Inbox` имеет объём ровно 17 458 байт, декодируется в UTF-8 без ошибок и имеет истинный SHA-256:
  `010412b209b22b399f1c1ea64b06fb2e3dfa98d7974a65f63462ee2db7a8994f`.
- **Устранение**: Хеш синхронизирован во всех трёх отчётных документах (`reports/LATEST.md`, `reports/POSTFIX_PILOT_READINESS_015.md`, `reports/postfix_pilot_readiness_015.json`). Ошибочный хеш полностью исключён.
- **Инварианты**: Кодовые файлы, тестовые матрицы, конфигурация, индексы и продакшн не изменялись; `git diff` ограничен исключительно тремя отчётными файлами.

---

## 2. Результаты верификации матриц тестов

### 2.1. Матрица ТЗ-015 Rev 1.3 (E15-01 .. E15-08)
Набор тестов: `tests/test_postfix_pilot_real_payload_015_rev1_3.py` (8 тестов, 2.306 с):
1. **E15-01**: Нативный derived hit Q004 без поля `norm` — извлечение СП 7 из `file_name` даёт `TARGET_DOC_MATCH=PASS`, `TARGET_CLAUSE_MATCH=PASS`, `SOURCE_FIDELITY=UNKNOWN`, `QUALITY_VERIFIED=False` (**PASS**).
2. **E15-02**: Нативный Q010 с `evidence_status='EVIDENCE_PARTIAL'` и отсутствием фрагмента EI 15 (без символов `...`) — немедленный `FULL_CLAUSE_EVIDENCE=FAIL`, `QUALITY_VERIFIED=False` (**PASS**).
3. **E15-03**: Q010 со сшитыми `parent_ids` [0021, 0022], наличием EI 60 и EI 15, без утечки в раздел 7 — границы `PASS`, но без независимого источника `SOURCE_FIDELITY=UNKNOWN`, `QUALITY_VERIFIED=False` (**PASS**).
4. **E15-04**: Нативный Q088-2020: `file_name` с 2020 -> `TARGET_EDITION_MATCH=PASS`; `file_name` с 2012 -> `FAIL`; упоминание «2020» только в тексте чанка при отсутствии года в имени файла -> `UNKNOWN`, не `PASS` (**PASS**).
5. **E15-05**: Запрос пункта 6.10: чанк с пунктом 6.100 -> `TARGET_CLAUSE_MATCH=FAIL`; чужой контекст с цитатой `(см. п. 6.10)` -> `UNKNOWN`, не `PASS` (**PASS**).
6. **E15-06**: Нативный векторный хит с `chunk_id` и `parent_id`, но без полей `section`/`derived_label`/года: `HAS_PAGE_OR_VALID_LOCATOR=PASS`, но `TARGET_CLAUSE_MATCH=UNKNOWN` (**PASS**).
7. **E15-07**: Совместимость с синтетическими фикстурами Rev 1.2 — при передаче эталонного текста источника `SOURCE_FIDELITY=PASS` и `QUALITY_VERIFIED=True` (**PASS**).
8. **E15-08**: Механическая пара OFF/ON с идентичным рангом и `success=True`, но неполным качеством: `MECHANICAL_PAIR_OK=True`, `QUALITY_VERIFIED=False`, `PILOT_QUALITY='UNVERIFIED'` (**PASS**).

### 2.2. Матрица ТЗ-015 Rev 1.2 (G15-R12-01 .. G15-R12-10)
Набор тестов: `tests/test_postfix_pilot_fail_closed_015_rev1_2.py` (10 тестов, 9.948 с) — **10/10 PASS**.

### 2.3. Матрица ТЗ-015 Rev 1.1 (P15-01 .. P15-10)
Набор тестов: `tests/test_postfix_pilot_fail_closed_015.py` (10 тестов, 6.869 с) — **10/10 PASS**.

### 2.4. Регрессионный набор тестов ТЗ-014 (RQ14, F1..F10, N1..N8, H1..H10)
Набор тестов: `tests/test_retrieval_clause_edition_014.py` (42 теста, 49.659 с) — **42/42 PASS**.

**Итого по локальному самоотчёту исполнителя: 70/70 PASS (0 ошибок, 0 падений, 0 регрессий).**

---

## 3. Официальные вердикты гейтов (Rev 1.3 / Rev 1.4 Errata)

| Гейт | Требование | Фактический статус | Обоснование |
| :--- | :--- | :--- | :--- |
| **G-REPORT-PROVENANCE**| Полное совпадение SHA-256 исходного ТЗ в трёх отчётах | **GO (PASS)** | SHA-256 `010412b209b22b399f1c1ea64b06fb2e3dfa98d7974a65f63462ee2db7a8994f` согласован в LATEST, MD и JSON. |
| **G-LIVE-PREV** | 0 реальных вызовов корпуса до прямого одобрения оператора | **VERIFIED (0 calls)** | Стенд проверен в синтетическом режиме. `actual_corpus_search_calls = 0`. |
| **G-REAL-PAYLOAD** | Совместимость оценщика с нативными полями MCP FlyingRAG | **GO (PASS)** | Поддержка `file_name`, `source_path`, `section`, `derived_label`, `clause_status`, `evidence_status`, `parent_ids`. |
| **G-SOURCE-FIDELITY** | Запрет автоматической сертификации источника | **GO (PASS)** | Без эталонного текста источника `SOURCE_FIDELITY = UNKNOWN`, `QUALITY_VERIFIED = False`. |
| **G-EDITION-STRICT** | Запрет признания редакции 2020 по тексту чанка | **GO (PASS)** | Только `FILENAME_INFERRED` или `SOURCE_METADATA`; по тексту — `UNKNOWN` / `FAIL`. |
| **G-PROD-INVARIANT** | Неизменность рабочей базы `metadata.db` | **VERIFIED (PASS)** | Размер `metadata.db` 1 485 103 104 байт, WAL = 0 байт, дата: 11.11.2026. |
| **G-LANCEDB-NO-UPGRADE**| Запрет переиндексации и обновления LanceDB | **VERIFIED (PASS)** | Без изменений пакетов и индекса. |
| **G-WATCHER-PAUSE** | Активность предохранителя `watcher.pause` | **VERIFIED (ACTIVE)** | Файл `watcher.pause` на месте, рабочий watcher остановлен. |

---

## 4. Состояние готовности к 6 поисковым вызовам

Подготовительный цикл кода ТЗ-015 закрыт (`HARNESS_REAL_PAYLOAD_CONTRACT: GO`).  
Документальный provenance подтверждён (`REPORT_PROVENANCE_GATE: GO`).  
Фактических поисковых вызовов по корпусу выполнено: **0**.  
Для запуска 6 реальных вызовов стенд ожидает текстовую директиву оператора:

> **«Разрешаю ТЗ-015 выполнить ровно 6 реальных поисковых вызовов Q004, Q010, Q088-2020 (3 пары EIG OFF/ON) на проверенной существующей изолированной копии, без любых изменений production».**
