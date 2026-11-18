# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.9 — POST-FIX RETRIEVAL EVIDENCE PILOT (ТЗ `FR-TZ-20261118-015` / Редакция 1.0 от 18.11.2026, SHA-256 `21b394691a78989b6879c0d4844e574e0a77236efb90092f7abeca1a6cbe5145`, 27 272 байта)  
**Статус этапа**: **`WAITING_OPERATOR_SEARCH_APPROVAL` / `ACTUAL_CORPUS_SEARCH_CALLS: 0` / `ISOLATED_COPY_VERIFIED: YES` / `CONSISTENT_SNAPSHOT: UNVERIFIED` / `MODEL_INDEX_IDENTITY: UNVERIFIED` / `PRODUCTION_METADATA_UNCHANGED: VERIFIED` / `LANCEDB_UPGRADE: DEFERRED_NO_CHANGES` / `WATCHER_PAUSE: ACTIVE` / `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Проверенное предусловие DEP-014**: **`SATISFIED`** (ТЗ-014 закрыто: коммит кода [`af984382c75a9a9844209dab96350e31d39df804`](https://github.com/Kritik35/flying-rag-mcp/commit/af984382c75a9a9844209dab96350e31d39df804), коммит отчёта [`271ec6183601d045b010f544267198f5af3ed2a1`](https://github.com/Kritik35/flying-rag-mcp/commit/271ec6183601d045b010f544267198f5af3ed2a1), тесты: 42/42 PASS в модуле, 73/73 PASS в регрессии)  
**Родительский коммит (preceding reports HEAD ТЗ-014 Rev 1.3)**: [`271ec6183601d045b010f544267198f5af3ed2a1`](https://github.com/Kritik35/flying-rag-mcp/commit/271ec6183601d045b010f544267198f5af3ed2a1)  
**Коммит кода ТЗ-014 Rev 1.3**: [`af984382c75a9a9844209dab96350e31d39df804`](https://github.com/Kritik35/flying-rag-mcp/commit/af984382c75a9a9844209dab96350e31d39df804)  
**Коммит отчёта ТЗ-014 Rev 1.2**: [`66b68c3fd3b06f3fb17a69a9a8b317bf11e5870e`](https://github.com/Kritik35/flying-rag-mcp/commit/66b68c3fd3b06f3fb17a69a9a8b317bf11e5870e)  
**Коммит кода ТЗ-014 Rev 1.2**: [`9f3ca6401366386b021e8fc151352b7ede172d96`](https://github.com/Kritik35/flying-rag-mcp/commit/9f3ca6401366386b021e8fc151352b7ede172d96)  
**Коммит отчёта ТЗ-014 Rev 1.1**: [`3108aba76df1004df7240ed27b2ce084d35b1e69`](https://github.com/Kritik35/flying-rag-mcp/commit/3108aba76df1004df7240ed27b2ce084d35b1e69)  
**Коммит кода ТЗ-014 Rev 1.1**: [`248cd4b5a415d9a52fd65662ac65ed040a8d966f`](https://github.com/Kritik35/flying-rag-mcp/commit/248cd4b5a415d9a52fd65662ac65ed040a8d966f)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый READ-ONLY)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1 485 103 104 байт, WAL: 0 байт, mtime: `1794429401.7884293` — строго неизменна)  
**Реальные поисковые вызовы к корпусу для текущей задачи**: **СТРОГО 0** (`actual_corpus_search_calls = 0`)  
**Режим**: STRICT OFFLINE / PREFLIGHT VERIFICATION / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH / NO AMEND  

---

## 1. Итоги предварительной подготовки к пилоту (ТЗ-015)

1. **Верификация изолированного снимка корпуса**:
   - Каталог `C:\Users\almax\AppData\Local\Temp\flying_rag_isolated_pilot_corpus_FR011` проверен: `metadata.db` (1 485 103 104 байт, `quick_check: ok`, `integrity_check: ok`), LanceDB `documents_1024` и 1 954 файла Parquet присутствуют и доступны.
   - Конфигурация `isolated_config.yaml` не содержит утечек в production.
   - Статус: `ISOLATED_COPY_VERIFIED: YES`, `CONSISTENT_SNAPSHOT: UNVERIFIED`.

2. **Телеметрия сервиса эмбеддингов**:
   - Эндпоинт `127.0.0.1:8089` проверен (`HTTP 200 ok`), модель `Qwen3-Embedding-0.6B-Q8_0.gguf`, размерность 1024, PID 2404.
   - Статус совместимости: `MODEL_INDEX_IDENTITY: UNVERIFIED`.

3. **Синтетическая проверка блокировки неоднозначных редакций**:
   - Запрос `СП 60.13330 п. 7.1.1` без года блокируется до кэша и поиска со статусом `ambiguous_editions`.

4. **Готовность стенда к проведению 6 поисковых вызовов**:
   - Подготовлен скрипт `tests/postfix_pilot_harness_015.py` и шаблон `reports/postfix_pilot_results_015_template.json`.
   - Режим по умолчанию `--dry-run` пройден успешно.
   - До получения отдельного согласия оператора живые поисковые вызовы заблокированы: **`actual_corpus_search_calls = 0`**.

---

## 2. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`STATUS`** | **`WAITING_OPERATOR_SEARCH_APPROVAL`** | Все подготовительные шаги завершены, ожидается санкция на 6 живых вызовов. |
| **`ACTUAL_CORPUS_SEARCH_CALLS`** | **`0`** | Новых поисковых вызовов к корпусу в рамках подготовки выполнено: строго 0. |
| **`ISOLATED_COPY_VERIFIED`** | **`YES`** | Изолированная копия в temp проверена, целостность SQLite подтверждена. |
| **`CONSISTENT_SNAPSHOT`** | **`UNVERIFIED`** | Последовательное копирование компонентов не гарантирует транзакционной синхронности. |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Совпадение размерности 1024 не доказывает идентичности весов и токенизатора. |
| **`PRODUCTION_METADATA_UNCHANGED`** | **`VERIFIED`** | Боевая база `metadata.db` не модифицировалась (1 485 103 104 байт, WAL 0 байт). |
| **`LANCEDB_UPGRADE`** | **`DEFERRED_NO_CHANGES`** | Обновление библиотек и формата таблиц LanceDB отложено. |
| **`WATCHER_PAUSE`** | **`ACTIVE`** | Стоп-маркер `watcher.pause` на станции Acer активен. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остается строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 3. Детальные отчёты этапа

- [POSTFIX_PILOT_READINESS_015.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/POSTFIX_PILOT_READINESS_015.md) / [postfix_pilot_readiness_015.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/postfix_pilot_readiness_015.json) — Отчёт о готовности к пост-фикс пилоту (ТЗ-015 Редакция 1.0).
- [RETRIEVAL_CLAUSE_EDITION_014.md](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/RETRIEVAL_CLAUSE_EDITION_014.md) / [retrieval_clause_edition_014.json](file:///C:/Acer_System_Audit/rag_quality_ab_20261113/worktree_stage3/reports/retrieval_clause_edition_014.json) — Отчёт о реализации точного извлечения пунктов норм, защите от нумерованных списков, величин, аутентификации межуровневых заголовков (Errata Rev 1.3) и машинном различении редакций документов (ТЗ-014 Редакция 1.3).
