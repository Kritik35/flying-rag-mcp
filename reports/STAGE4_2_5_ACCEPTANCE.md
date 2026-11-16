# FlyingRAG — Отчёт независимой приёмки Stage 4.2.5
## Google Drive Inbox Bootstrap + Controlled Shadow Pilot

**Дата приёмки**: 2026-11-16
**Проект**: `Kritik35/flying-rag-mcp`
**Рабочая ветка**: `audit/stage4-2-verification`
**Протестированный коммит кода (Tested Code Commit)**: [`74c0ade8608da33c5ee0debf5c930597d0af5a2e`](https://github.com/Kritik35/flying-rag-mcp/commit/74c0ade8608da33c5ee0debf5c930597d0af5a2e)
**Tree SHA**: `2110a754ab12aa9af6e2084abfc096a6cdf319f0`
**Run ID**: `stage4_2_5_20261116_095827_74c0ade8`
**Базовый анкор (Baseline Anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95`
**Снимок аудита (Snapshot Anchor)**: `4f43949aa9c03e7ccd99d1ce072d954f18f8c786` (`audit/stage4-1-snapshot-20261115`)
**Режим приёмки**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX

---

## 1. Независимые вердикты этапа Stage 4.2.5

| Компонент / Направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **Google Drive Inbox Monitor** | **`MONITOR_READY_DETECTION_ONLY`** | Блок **M0** полностью закрыт: служба мониторинга развёрнута и проверена в режиме `DETECTION_ONLY`. Windows Task Scheduler зарегистрирован на запуск каждые 5 минут (`FlyingRAG_Drive_Inbox_Watcher`). Кросс-процессный мьютекс через `msvcrt.locking` исключает параллельные запуски. Облачные ярлыки `.gdoc`/`.gsheet` безопасно пропускаются без попыток чтения reparse point DriveFS. Базовый bootstrap зафиксировал существующий файл `FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt` в статусе `ACKNOWLEDGED` без ложных триггеров. |
| **Shadow Operational Readiness** | **`GO`** | Блоки **S1–S5** закрыты: устранена зависимость от CWD через явную привязку `(ROOT / ctrl_file_path).resolve()`, повреждённый или отсутствующий файл управления безопасно отключает адаптер (`FAIL_SAFE_DEFAULT`). В бенчмарке из 105 запросов (80 реальных нормативных + 25 adversarial) доказана 100% побайтная идентичность сериализации и сохранение ранжирования. Средний оверхед диспетчеризации составил **0.11 мс** ($p_{50}=0.06 мс, p_{95}=0.21 мс, p_{99}=1.65 мс, max=1.95 мс, 0 сбоев, 0 дропов). |
| **Indexer Safety Verification** | **`GO`** | Блоки **I1–I2** закрыты: введена глубокая проверка отката LanceDB через канонический дайджест каждой строки (`chunk_id`, `doc_id`, `text`, `text_hash`, `metadata`, `vector.tobytes()`). Любое расхождение векторов или текста детектируется с возбуждением критического исключения `RuntimeError`. Проверен контракт согласованности окон сбоев между SQLite и LanceDB. База данных production не затронута. |

---

## 2. Сводка результатов тестирования (Gate Matrix)

- **Общий статус приёмки**: **PASSED**
- **Всего проверок выполнено**: **145**
- **Успешно**: **145** (100.0%)
- **Сбоев / Ошибок**: **0**
- **База данных Production**: **UNTOUCHED (True)** — размер 1,485,103,104 байт, хеш среза и нулевой размер WAL неизменны.
- **Чистота рабочей директории**: **Clean (True)** на момент тестирования.

### Результаты по гейтам (Gates G0 — G8, M0, S5)
| Гейт | Название | Статус | Тестов | Описание |
|:---|:---|:---:|:---:|:---|
| **G0** | Environment Isolation & Baseline Anchor | **PASSED** | 6 / 6 | Изоляция worktree, соответствие baseline production, неизменность snapshot, криптографический префлайт БД |
| **M0** | Google Drive Inbox Watcher & Bootstrap | **PASSED** | 8 / 8 | Google Drive Inbox Watcher: Windows Task Scheduler, mutex msvcrt.locking, безопасный пропуск .gdoc, bootstrap |
| **G1** | P0 Indexer Fix, Upsert Atomicity & Vector Cache Integrity | **PASSED** | 31 / 31 | Глубокая сверка отката LanceDB (канонический дайджест строк и векторов), префлайт, транзакции SQLite и контракт согласованности |
| **G2** | Multi-chunk Sequential Stitching & Coordinate Invariants | **PASSED** | 9 / 9 | Склейка смежных чанков, инварианты координат codepoints, отказ от конкатенации без перекрытия |
| **G3** | Formula & Mathematical Integrity Gate | **PASSED** | 5 / 5 | Детекция математических уравнений, изоляция ссылок без тела формулы, отказ скалярных присвоений |
| **G4** | Topic Alignment & Evidence Status Synthesis | **PASSED** | 15 / 15 | Защита от ложных отказов, детекция формульных запросов с понижением статуса, обработка общих тем |
| **G5** | Document & Edition Disambiguation / SQLite RO URI | **PASSED** | 4 / 4 | Точные границы токенов (СП 7 vs СП 70), детекция мультиредакций, read-only enforce в SQLite |
| **G6** | Shadow Adapter Safety, Congruence & MCP Path Isolation | **PASSED** | 35 / 35 | Shadow Adapter: детерминированное разрешение путей control_file, bounded shutdown, cancel pending, fail-safe disabled |
| **G7** | Adversarial Test Suite & Latency Distribution | **PASSED** | 25 / 25 | Adversarial Test Suite: 25 стресс-запросов, средняя задержка 41.03 мс (Wall), медиана 35.53 мс, p95 57.95 мс |
| **S5** | Shadow Pilot 105-Query Paired-Delta Benchmark | **PASSED** | 1 / 1 | Shadow Pilot 105-Query Benchmark: 80 нормативных + 25 adversarial, 100% побайтная сериализация, rank match, оверхед 0.11 мс |
| **G8** | Production Read-Only Source Fidelity & OOXML Audit | **PASSED** | 5 / 5 | Production Read-Only Source Fidelity & OOXML Audit: инварианты СП 7 / СП 60, пропуск OMML в python-docx |
| **Post**| Database Postflight Integrity Check | **PASSED** | 1 / 1 | Database Postflight Integrity Check: полное совпадение контрольных сумм и mtime базы данных до и после всех тестов |

---

## 3. Детальный отчёт по блоку M0 (Google Drive Inbox Watcher & Bootstrap)

1. **Развёртывание службы и изоляция**:
   - Реализован автономный скрипт `scripts/drive_inbox_watcher.py` с поддержкой режимов `--run-once`, `--bootstrap` и `--status`.
   - Конфигурация службы:
     - Папка инбокса: `G:\Мой диск\FlyingRAG_TZ_Inbox`
     - Хранилище состояния: `C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\state.json` (строго за пределами Git и production).
     - Режим работы: `DETECTION_ONLY` (запрещено несанкционированное выполнение команд или скриптов).
2. **Кросс-процессный мьютекс (Windows File Lock)**:
   - Вход в цикл проверки защищён блокировкой файла `state.lock` через системный вызов `msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)`.
   - При повторном запуске во время активного цикла второй процесс немедленно завершается с информационным статусом без конфликтов записи.
3. **Безопасная обработка облачных ярлыков (.gdoc / .gsheet)**:
   - На виртуальном диске Google Drive for Desktop (`G:\`) файлы `.gdoc` представляют собой виртуальные Reparse Point размером 253 байта, чтение которых стандартными файловыми дескрипторами Windows возвращает ошибку `[Errno 22] Invalid argument`.
   - В `drive_inbox_watcher.py` файлы с расширениями `.gdoc` и `.gsheet` безопасно детектируются по расширению и пропускаются без попыток прямого открытия.
4. **Интеграция с Windows Task Scheduler**:
   - Зарегистрирована системная задача: `FlyingRAG_Drive_Inbox_Watcher`.
   - Расписание: каждые 5 минут (`/sc minute /mo 5`).
   - Командная строка: `C:\RAG_Acer\venv\Scripts\python.exe scripts\drive_inbox_watcher.py --run-once`.
   - Выполнена контрольная проверка триггера через `schtasks /run` — статус `SUCCESS`.
5. **Базовый Bootstrap**:
   - При первичном запуске с ключом `--bootstrap` существующий файл `FR-TZ-20261115-001_Stage4.2.5_FlyingRAG.txt` внесён в реестр со статусом `ACKNOWLEDGED`, исключая повторные генерации событий.

---

## 4. Детальный отчёт по блоку S5 (Shadow Pilot 105-Query Benchmark & Hardening)

1. **Детерминированное разрешение путей control_file**:
   - В `rag_server/server.py:133-138` устранена зависимость от текущей рабочей директории процесса (CWD).
   - Относительный путь к файлу управления гарантированно разрешается от корня приложения: `(ROOT / ctrl_file_path).resolve()`.
   - В тесте `test_control_file_relative_path_resolution_independent_of_foreign_cwd` подтверждена корректная работа сервера при запуске из произвольной временной директории.
2. **Безопасный отказ при повреждении конфигурации (Fail-Safe Disabled)**:
   - При отсутствии настроенного файла управления или повреждении его JSON-структуры адаптер не падает, а безопасно остаётся в состоянии `enabled=False, reason="FAIL_SAFE_DEFAULT"`.
3. **Бенчмарк из 105 запросов (Paired-Delta Benchmark)**:
   - Нагрузочный набор включает 80 реальных нормативных запросов по СП 60, СП 7, СП 1, СП 70 и 25 adversarial стресс-запросов.
   - **Побайтная идентичность вывода MCP**: 100% совпадение (`json.dumps(payload_enabled) == json.dumps(payload_disabled)`).
   - **Сохранение ранжирования**: 100% эквивалентность рангов и списков результатов.
   - **Оверхед диспетчеризации (Dispatcher Overhead)**:
     - Медиана ($p_{50}$): **0.06 мс**
     - Среднее: **0.11 мс**
     - 95-й процентиль ($p_{95}$): **0.21 мс**
     - 99-й процентиль ($p_{99}$): **1.65 мс**
     - Максимум: **1.95 мс**
     - Потери задач / сбои: **0 / 0** (все 105 запросов обработаны штатно).

---

## 5. Детальный отчёт по безопасности индексатора (Блок I2)

1. **Канонический дайджест строк и векторов LanceDB**:
   - В `storage/vector_store.py:351-375` реализован метод вычисления канонического SHA256-дайджеста строки `_row_canonical_digest(row)`.
   - Дайджест включает: `chunk_id`, `doc_id`, `text`, `text_hash`, нормализованные метаданные и побайтовое представление вектора `vector.astype(np.float32).tobytes()`.
   - В процессе отката таблица восстанавливает исходный срез и проверяет побайтовый дайджест каждой восстановленной строки.
   - В тесте `test_rollback_deep_digest_fails_on_altered_vector_or_text_despite_matching_id_and_count` подтверждено, что попытка подмены текста или смещения вектора немедленно вызывает `RuntimeError("CRITICAL: LanceDB rollback content/vector digest mismatch")`.
2. **Контракт согласованности окон сбоев между хранилищами (Cross-Store Window)**:
   - В `test_cross_store_failure_window_reconciliation_contract` проверен сценарий сбоя на этапе фиксации в SQLite после успешной записи в LanceDB:
   - LanceDB успешно откатывает добавленные строки к предыдущей версии с глубокой проверкой дайджеста.
   - Транзакция SQLite откатывается штатным механизмом rollback.
   - Исходные данные обоих хранилищ остаются в 100% согласованном состоянии.

---

## 6. Профиль производительности (Gate G7)

- **Всего adversarial-запросов**: **25**
- **Средняя задержка (Wall-Clock)**: **`41.03 ms`**
- **Средняя задержка (CPU Time)**: **`36.88 ms`**
- **Медиана ($p_{50}$)**: **`35.53 ms`**
- **95-й процентиль ($p_{95}$)**: **`57.95 ms`**
- **99-й процентиль ($p_{99}$)**: **`59.72 ms`**
- **Минимальная задержка**: **`27.42 ms`**
- **Максимальная задержка**: **`60.06 ms`**
- **Суммарное время набора (25 запросов)**: **`1.03 s`**

---

## 7. Оставшиеся дефекты и риски (Top-3 Residual Risks)

1. **Пропуск формул OOXML в парсере**: Стандартный `python-docx` опускает теги `<m:oMath>`, из-за чего в базе сохраняется только метка `(А.3)` без тела формулы. EIG безопасно детектирует это как `FORMULA_MISSING` -> `EVIDENCE_PARTIAL`. Устранение требует модернизации парсера и полного переиндексирования корпуса (в будущих релизах при снятии запрета NO REINDEX).
2. **Неопределённость редакции без указания года**: Запросы без указания года нормативного документа (например, «СП 60.13330 п. 7.1.1») классифицируются как `AMBIGUOUS_SOURCE` -> `REFUSAL_REQUIRED`.
3. **Физическая недоступность диска H:**: Оригинальные файлы на несмонтированном диске H: помечаются как `SOURCE_NOT_VERIFIED (BLOCKED_BY_SOURCE_UNAVAILABLE)`.

---

## 8. Ссылки на подробные технические артефакты

- **Машинно-читаемые результаты гейтов**: [`reports/stage4_2_5_gate_results.json`](stage4_2_5_gate_results.json)
- **Матрица тестов (145 проверок)**: [`reports/stage4_2_5_test_matrix.json`](stage4_2_5_test_matrix.json)
- **Отчёт службы мониторинга Drive**: [`reports/stage4_2_5_drive_watcher.json`](stage4_2_5_drive_watcher.json)
- **Метрики бенчмарка Shadow Pilot**: [`reports/stage4_2_5_shadow_pilot.json`](stage4_2_5_shadow_pilot.json)
- **Доказательства безопасности индексатора**: [`reports/stage4_2_5_indexer_recovery.json`](stage4_2_5_indexer_recovery.json)
- **Провенанс и криптографические контрольные суммы**: [`reports/stage4_2_5_provenance.json`](stage4_2_5_provenance.json)
- **Достоверность первоисточников**: [`reports/stage4_2_5_source_fidelity.json`](stage4_2_5_source_fidelity.json)
- **Постоянный регламент отчётности**: [`docs/AGENT_REPORTING_PROTOCOL.md`](../docs/AGENT_REPORTING_PROTOCOL.md)
