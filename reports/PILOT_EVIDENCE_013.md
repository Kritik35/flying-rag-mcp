# Отчёт о проверке качества реального поиска: ТЗ-013 (POST-PILOT-QUALITY-01)

**Документ**: Отчёт о детальной проверке достоверности результатов пилота, границ чанков и первоисточников норм (ТЗ `FR-TZ-20261117-013`, Редакция 1.0 от 17.11.2026)  
**Техническое задание**: `FR-TZ-20261117-013` / `POST-PILOT-QUALITY-01`  
**SHA-256 ТЗ**: `ad034f9dd103f4649fbb9922202af17a17e39824acd24d0f34225dfe89a35db5` (20 931 байт)  
**Локальный путь ТЗ**: [FR-TZ-20261117-013_POST_PILOT_SOURCE_FIDELITY_8aad1223_FlyingRAG.txt](<FILE_URI_REDACTED>)  
**Дата завершения**: 18 ноября 2026 года  
**Официальный вердикт**: **`REAL_SEARCH_CALLS_VERIFIED: 6` / `SOURCE_FIDELITY: WRONG_CLAUSE_TOPIC (Q004) / TRUNCATED (Q010) / AMBIGUOUS_EDITIONS (Q088)` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `EMBEDDING_RUNTIME: HEALTHY_REPORTED` / `PERFORMANCE_CAUSALITY: NOT_ESTABLISHED` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `PRODUCTION_SQLITE_UNCHANGED: VERIFIED` / `BOOT_RECOVERY: CONFIGURED_UNOBSERVED` / `WATCHER_PAUSE: ACTIVE`**

---

## 0. Git Provenance и цепочка коммитов

- **Репозиторий**: `https://github.com/Kritik35/flying-rag-mcp`
- **Ветка аудита**: `audit/stage4-2-verification`
- **Проверенный кодовый якорь (тесты фикстур Phase A)**: [`1c02df6992d9d153efc1aa1aa081230198e3b50c`](https://github.com/Kritik35/flying-rag-mcp/commit/1c02df6992d9d153efc1aa1aa081230198e3b50c) (Tree: `42702d341efe58d8ca28491e5a1391c9fd6d1757`)
- **Предыдущий отчётный коммит (reports HEAD Phase B ТЗ-012)**: [`e19771ba07c6f0072b22bb8fa81699f807205fa6`](https://github.com/Kritik35/flying-rag-mcp/commit/e19771ba07c6f0072b22bb8fa81699f807205fa6) (Tree: `a5211ccfa263a59e4cf6389fdd5eb2434d7fc62c`)
- **Коммит выполнения поискового смоук-теста (Phase B ТЗ-011 Rev 1.1)**: [`8aad12237ca51c510f4ee446f5a4366f118d67af`](https://github.com/Kritik35/flying-rag-mcp/commit/8aad12237ca51c510f4ee446f5a4366f118d67af) (Tree: `f80ef1f486dd817260c52d2d879eb34033c07371`)
- **Боевой базовый коммит (clean READ-ONLY)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`).

---

## 1. P0-А — Доказательство реальности 6 поисковых вызовов

Выполнение 6 вызовов на изолированной копии (`<ISOLATED_TEMP_CORPUS>`) подтверждено фактическими артефактами:

1. **Исполняемые файлы и окружение**:
   - Python-интерпретатор: `<PRODUCTION_DIR>/python.exe`.
   - Воркер: `tests/shadow_pilot_worker.py`.
   - Харнесс: `scratch/run_pilot_action_c.py` (7 279 байт, SHA-256: `e684ca8b...`, mtime: `1794948224.323`).
2. **Артефакты результатов и логов**:
   - `pilot_smoke_results.json` (4 643 байта, SHA-256: `96c00afa...`, mtime: `1794948376.388`).
   - `shadow_eig.log` (3 743 байта, SHA-256: `43cf8e13...`, mtime: `1794948376.176`).
   - `isolated_config.yaml` (822 байта, SHA-256: `d925eb95...`).
3. **Отсутствие симуляции**:
   - Командная строка вызова воркера формировалась строго без аргументов `--simulated-result` и `--simulated-error`.
   - Трассировка выполнения:  
     `run_pilot_action_c.py` $
ightarrow$ subprocess `shadow_pilot_worker.py` $
ightarrow$ `rag_server.server._dispatch('search_documents')` $
ightarrow$ `rag_server.tools.search_documents` $
ightarrow$ чтение реальной SQLite/LanceDB в системном TEMP.
4. **Происхождение меток `top_chunk`**:
   - Метки `clause_6.4`, `clause_6.10`, `clause_7.1.1` **не являются физическими chunk_id в LanceDB** (где формат `973d9901_c_XXXX`).
   - Это **динамически формируемые derived labels**, которые модуль `norm_reg.extract_clause_from_doc` в `rag_server/tools.py` генерирует при обнаружении в запросе конкретного пункта нормы и помещает на 1 место в `quality_pool` с `doc_id = 'norm_lookup'`.

---

## 2. P0-Б — Проверка первоисточников и границ чанков (Q004, Q010, Q088)

Детальная сверка с первоисточниками в базе `metadata.db` выявила конкретные несоответствия:

| ID запроса | Текст запроса | Первичный документ | Первичный chunk / parent ID | Реальный текст в БД | Вердикт соответствия |
|:---|:---|:---|:---|:---|:---:|
| **Q004** | `СП 7.13130 пункт 6.4` | `СП 7.13130.docx` | `973d9901_p_0017` / `0018` | *«6.4 В пределах одного пожарного отсека общие приемные устройства наружного воздуха не следует предусматривать...»* | **`WRONG_CLAUSE_TOPIC`** |
| **Q010** | `СП 7.13130 пункт 6.10` | `СП 7.13130.docx` | `973d9901_p_0021` (начало), `973d9901_p_0022` (окончание) | В `0021` перечень клапанов обрывается; числовые пределы EI 30 / EI 15 находятся в чанке `0022`. | **`TRUNCATED / EVIDENCE_PARTIAL`** |
| **Q088** | `СП 60.13330 пункт 7.1.1` | `СП 60.13330.2020...docx` | `3fb687c5_p_0038` (пункт), `3fb687c5_p_0037` (предшеств.) | Пункт 7.1.1 — *«Вентиляцию следует применять...»*. Ссылка на 6.4.14 попала из предшествующего чанка `0037`. В базе есть редакции 2012 и 2020 годов. | **`AMBIGUOUS_EDITIONS / REFUSAL_REQUIRED`** |

### Детальные выводы по первоисточникам:
1. **Q004**: В манифесте запросов для Q004 была заявлена гипотеза «Пределы огнестойкости воздуховодов». Однако реальный пункт 6.4 СП 7.13130 посвящён **приёмным устройствам наружного воздуха**. Пределы огнестойкости воздуховодов нормируются пунктами 6.18 / 6.22. Поиск нашёл точный пункт 6.4, но гипотеза эталона оказалась ошибочной (`GOLD_UNVERIFIED_TOPIC_MISMATCH`).
2. **Q010**: Пункт 6.10 СП 7.13130 содержит обширный перечень требований. Из-за фиксированного окна чанкинга пункт разорван на границе: подпункт «а» попал в чанк `0021`, а пределы огнестойкости (EI 30, EI 15) для воздушных затворов — в чанк `0022`. Теневой EIG обоснованно зафиксировал `TRUNCATED` / `EVIDENCE_PARTIAL`.
3. **Q088**: Запрос не содержит года редакции. В индексе присутствуют две действующие в разных контекстах редакции: `СП 60.13330.2012` и `СП 60.13330.2020`. Теневой EIG зафиксировал коллизию: `SOURCE_AMBIGUOUS` / `REFUSAL_REQUIRED`. Попадание текста п. 6.4.14 в сниппет объясняется тем, что `extract_clause_from_doc` берёт родительский чанк целиком, захватывая контекст предшествующего раздела.

---

## 3. P0-В — Вердикты модели, инвариант EIG и причинность задержек

1. **Статусы модели**:
   - `EMBEDDING_RUNTIME: HEALTHY_REPORTED` (сервер 8089 возвращает векторы 1024-d, все значения конечные).
   - `SEMANTIC_SANITY: PASS_REPORTED` (селективность 0.8756 для связанных запросов vs 0.2784 для несвязанных).
   - `MODEL_INDEX_IDENTITY: UNVERIFIED` (до проведения контрольного побитового замера против эталонного вектора из индекса).
2. **Инвариант пассивного наблюдения EIG**:
   - Во всех 3 парах клиентская выдача (все 5 возвращённых документов и чанков) в режиме ON **на 100% совпала** с режимом OFF (`rank_and_payload_identical: True`).
   - Теневой EIG не производит активной фильтрации или переранжирования.
3. **Причинность производительности (`PERFORMANCE_CAUSALITY: NOT_ESTABLISHED`)**:
   - Снижение задержки между первым вызовом OFF (~35–41 с) и вторым вызовом ON (~9–13 с) вызвано **прогревом дискового кэша SQLite и плана выполнения запросов** при повторном обращении, а не ускорением от включения EIG.
   - Утверждения об отрицательном оверхэде EIG признаны необоснованными.

---

## 4. P0-Г — Границы снимка и production-инвариант

1. **Изолированный снимок**:
   - Проверка `check_readonly_scope()` подтвердила безопасность путей (`ISOLATED_COPY_VERIFIED`).
   - Однако транзакционная синхронность SQLite и LanceDB остаётся **`CONSISTENT_SNAPSHOT: UNVERIFIED`** до внедрения SQLite Backup API и гарантированного quiescent window.
2. **Боевая база данных**:
   - Для `<PRODUCTION_DB_METADATA>` подтверждены неизменность размера (1 485 103 104 байт), mtime (`1794429401.7884293`) и нулевой WAL: **`PRODUCTION_SQLITE_METADATA_UNCHANGED_REPORTED`**.
   - Неизменность всего дерева каталогов production помечается честно: **`PRODUCTION_FULL_TREE_UNCHANGED: NOT_INDEPENDENTLY_VERIFIED`** (во избежание ложных заверений без полного пофайлового дайджеста).

---

## 5. P1 — Офлайн-фикстуры регрессионного качества

В тестовом наборе `tests/test_pilot_quality_regression_013.py` (коммит `1c02df69`, 5/5 тестов PASS) реализованы две изолированные фикстуры для выявленных дефектов:

1. **`CLAUSE_TABLE_COMPLETENESS`**:
   - Тест `test_clause_truncation_detection_sp7_6_10` проверяет распознавание разрыва таблицы или перечисления на границе чанка, возвращая `TRUNCATED` / `EVIDENCE_PARTIAL`.
   - Тест `test_clause_complete_boundary_sp7_6_4` подтверждает статус `COMPLETE` / `USABLE_FOR_ANSWER` при наличии закрывающей точки и сбалансированных скобок.
2. **`EDITION_DISAMBIGUATION`**:
   - Тест `test_edition_disambiguation_unspecified_year_collision` воспроизводит коллизию Q088: при запросе без года (`СП 60.13330`) и наличии редакций 2012 и 2020 возвращается `AMBIGUOUS_EDITIONS` с флагом `refusal_required: True`.
   - Тест `test_edition_disambiguation_explicit_year_matched` подтверждает корректную фильтрацию при явном указании года (`СП 60.13330.2020`).

---

## 6. Матрица проверок E7-01 .. E7-10

| Проверка | Критерий ТЗ-013 | Вердикт | Обоснование |
|:---|:---|:---:|:---|
| **E7-01** | Реальный диспетчерский путь без симуляции | **`PASS`** | 6 вызовов через `shadow_pilot_worker.py` $
ightarrow$ `_dispatch('search_documents')`, exit code 0, `--simulated-*` = None. |
| **E7-02** | Разделение derived labels и реальных ID | **`PASS`** | `clause_6.4/6.10/7.1.1` квалифицированы как derived labels; указаны первичные `parent_id` в SQLite. |
| **E7-03** | Q010: усечение таблицы $
ightarrow$ `EVIDENCE_PARTIAL` | **`PASS`** | Пункт 6.10 разорван между чанками `0021` и `0022`; статус `EVIDENCE_PARTIAL` подтверждён. |
| **E7-04** | Q088: неоднозначность 2012/2020 $
ightarrow$ `REFUSAL_REQUIRED` | **`PASS`** | Наличие двух редакций без года в запросе обоснованно требует отказа от выдачи несертифицированного ответа. |
| **E7-05** | Модель без индексного дайджеста $
ightarrow$ `UNVERIFIED` | **`PASS`** | Манифест совпадает, но криптографический замер эталона отложен. `MODEL_INDEX_IDENTITY: UNVERIFIED`. |
| **E7-06** | Задержки OFF/ON $
ightarrow$ causality не доказана | **`PASS`** | Разница задержек признана эффектом прогрева кэша (`PERFORMANCE_CAUSALITY: NOT_ESTABLISHED`). |
| **E7-07** | Инвариант выдачи EIG ON vs OFF | **`PASS`** | 100% совпадение выдачи и рангов для всех 5 возвращённых позиций. |
| **E7-08** | Неизменность SQLite != весь production | **`PASS`** | Честно разделены статусы `SQLITE_UNCHANGED: VERIFIED` и `FULL_TREE: NOT_INDEPENDENTLY_VERIFIED`. |
| **E7-09** | Согласованность копии != нахождение в temp | **`PASS`** | Физическая изоляция путей подтверждена, транзакционная синхронность — `UNVERIFIED`. |
| **E7-10** | Сохранность watcher и статуса boot recovery | **`PASS`** | `watcher.pause` активен, очередь работает штатно, `BOOT_RECOVERY: CONFIGURED_UNOBSERVED`. |

---

## 7. Ссылки на файлы этапа

- [test_pilot_quality_regression_013.py](<FILE_URI_REDACTED>)
- [PILOT_EVIDENCE_013.md](./PILOT_EVIDENCE_013.md)
- [pilot_evidence_013.json](./pilot_evidence_013.json)
- [LATEST.md](./LATEST.md)
