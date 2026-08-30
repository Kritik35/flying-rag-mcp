# Исследование LES → что берём во Flying RAG MCP

Дата: 2026-08-30. Источники: `proovcme/les_rag` (main + 34 ветки),
`Kritik35/les_rag_windows` (main + 10 веток), `Kritik35/flying-rag-mcp` (master).

Документ — карта находок и приоритизированный список заимствований.
Ничего из перечисленного ещё не внедрено.

## 1. Где мы находимся

Flying RAG MCP — ~13 000 строк Python, один процесс, Windows, локальный стек:
Lemonade (`/api/v1/embeddings`, `/api/v1/reranking`) + LanceDB + SQLite + MCP.

Контур поиска (`rag_server/tools.py:search_documents`):

```
query
  → query_router.route_query        детерминированный scope по YAML-терминам
  → query_planner.plan_query        1..5 подзапросов (hardcoded доменные расширения)
  → vector_store.search × N         LanceDB hybrid (LinearCombinationReranker, alpha=0.7)
  → fuse_ranked_results             RRF между подзапросами
  → retrieval_quality               дедуп/лимит на документ
  → rerank_policy → reranker        bge-reranker-v2-m3 через Lemonade
  → source_focus.concentrate        top-3 документа, min_score=0.30
  → crag.grade_retrieval            слабая выдача → один retry с аугментацией
  → semantic_cache
```

Это уже современное ядро: parent-child chunking, гибрид, cross-encoder, CRAG,
RRF, семантический кэш, детерминированные табличные суммы, ColPali для чертежей,
eval-харнесс Hit@k/MRR/P@k. Сильные стороны сохраняем.

## 2. Что такое LES

~186 000 строк Python. Qdrant (named dense + native sparse) + MLX/Lemonade +
SQLite FTS + FastAPI-прокси со 184 сервисами + Tauri-десктоп + модули смет,
нормоконтроля, почты, CAD/BIM. 372 тестовых файла. Полноценная документация
архитектуры: `ALGO-*`, `ADR-*`, `AUDIT_*`, `RELEASE_LEDGER`, `MODULE_INDEX`.

Их production-контур (`docs/ALGO-rag-best-practices.md`):

```
query → нормализация → scope → Qdrant named dense + BM25 sparse
     → RRF → SQLite FTS exact-safety merge → reranker по широкому пулу
     → exact identifier guard → parent/neighbor expansion
     → evidence packet → модель читает и отвечает
```

Ключевое отличие от нас: **всё измеряется и всё честно помечено**. Есть контракт
эмбеддингов, контракт индекса, контракт реранка, evidence-пакет с локаторами,
разделение navigation ≠ evidence.

### Обзор веток

`les_rag` — один длинный «stack» из ~10 веток, наслаивающихся друг на друга
(`codex/required-ocr` → `codex/index-contract-adoption-gate` →
`codex/ingestion-provenance-formats` → `codex/hierarchy-node-identity` →
`codex/search-reranker-and-scope` → `codex/private-integration-pr18-pr17`,
до +138 коммитов к main). Именно там живёт всё новое RAG-ядро:
`backend/index_contract_attestation.py` (536 строк), `backend/provenance.py` (214),
`backend/ingestion_ownership.py` (116), переработанный `ocr_parser.py`,
`converter.py`, +853 строки в `qdrant_adapter.py`, hierarchy v1.

Остальные ветки — продуктовые и платформенные: `codex/les-0.29.0-model-connections`,
`codex/les-0.30.0-bootstrap-updater`, `codex/lemonade-*` (4 шт.),
`codex/unified-harness-native-qdrant`, `feat/glorax-normcontrol`,
`codex/smeta-*`, `codex/rim-dialog-mvp`, `codex/vps-sovushka-ui-node`.
Для нас они интереса почти не представляют.

`les_rag_windows` — Windows-контур. Самая ценная ветка `fix/llama-cpp-embedding-contract`
(+95 коммитов): контракт эмбеддингов для llama.cpp-серверов, измеренные настройки
llama-server, паритет векторов, chunk-size provenance, fail-closed OCR.
Это ровно наш стек (Lemonade = llama.cpp).

## 3. Разрывы: где мы объективно слабее

### 3.1 Нет контракта эмбеддингов — главный риск

`embedder/client.py` отправляет `{"model": ..., "input": ...}` и берёт
`data["data"][i]["embedding"]`, **никогда не сверяя `data["model"]` с запрошенной
моделью**. Таблица LanceDB называется `documents_{dim}` — совместимость проверяется
только по размерности. Qwen3-Embedding-0.6B и bge-m3 оба дают 1024. Если Lemonade
после перезапуска отдаёт другую модель, запросы молча эмбеддятся чужой моделью
по корпусу, собранному первой. Симптом — «поиск стал хуже», причина невидима.

LES прошли ровно этот путь и записали правило:

> Нельзя сравнивать вектора разных embedding-моделей только потому, что у них
> одинаковая размерность.

У них это `EmbeddingContractError` + fail-closed, плюс `les.rag.index-contract.v2`
(коллекция, модель, размер вектора, tokenizer budget, чанкер, ревизия sparse).

### 3.2 Гибрид молча вырождается в vector-only

```python
except Exception as e:
    print(f"[vector_store] hybrid fallback to vector: {e}", file=sys.stderr)
    rows = []
```

Дальше идёт чистый векторный поиск, а `debug`-трейс продолжает описывать запрос
так же, как удачный гибрид. У LES это прямо запрещено: «маркировать
single-channel fallback как hybrid/RRF» — нельзя. Их `RetrievalTrace` несёт
`mode`, `fusion`, `score_kind`, `retrieval_channels`, `status`, `error_code`.

### 3.3 Пороги применяются к несопоставимым шкалам

`crag.grade_retrieval` сравнивает `results[0]["score"]` с 0.55/0.35. Но этот score
может прийти из `LinearCombinationReranker`, из RRF-бонуса `fuse_ranked_results`
(base + min(0.08, rrf*2)), из сигмоиды реранкера или из `1 - _distance`. Четыре
разные шкалы, один порог. LES явно фиксируют:

> Absolute score thresholds are valid only for a declared dense-similarity channel.
> Qdrant RRF, local RRF, FTS and cross-encoder logits are not cosine.

и переключаются на `term_coverage` + `source_diversity`, когда шкала не dense.

### 3.4 Домен дописывается в запрос — и это ломает наш же eval

`query_planner.plan_query` подмешивает в подзапросы готовые утверждения
(`"СП 7.13130 противодымная вентиляция дымоудаление требования"`),
`_RETRY_AUGMENT` дописывает то же на retry. При этом `scripts/eval_retrieval.py`
ждёт `expected_any: ["7.13130", "противодым"]`. То есть мы кладём в запрос
ровно те строки, которые потом ищем в выдаче.

LES провели этот аудит и оценили свою тестовую программу на **4/10**
(`docs/RAG_TEST_PROGRAM_AUDIT.md`): «live golden проверял `/api/rag/retrieve-debug`,
а endpoint дописывал ожидаемые FIRE/HVAC слова. Зелёный 16/16 не являлся
доказательством retrieval quality». После чистки — 7/10.

### 3.5 Нет локаторов — цитата не указывает на страницу

`parsers/pdf_vision.py` склеивает весь PDF в одну строку. Ни `page`, ни bbox
не доживают до чанка; в LanceDB нет колонки страницы. Мы физически не можем
ответить «СП 7.13130, стр. 14». LES ведут `provenance.v1` с типизированными
локаторами (`pdf_page`, `table_row`, `xlsx_row`, `cad_entity`, `ifc_guid`)
и SHA-256 источника.

### 3.6 OCR теряет данные молча

Три места:

* `ocr_page()` при ошибке возвращает строку `"[Ошибка распознавания страницы: ...]"`,
  и она уходит в индекс как обычный текст;
* `VISION_MAX_PAGES=5` — у сканированного PDF на 200 страниц индексируются пять,
  остальные исчезают без следа;
* `_is_raster_pdf` решает per-document (`total < 50 × pages`), поэтому смешанный
  PDF (часть страниц с текстовым слоем, часть сканы) считается текстовым,
  и сканы теряются целиком.

LES закрыли это `OCRProcessingError` (стабильный код ошибки, страница, fail-closed),
per-page маршрутизацией и порогом `chars/page < 20 → в OCR`.

### 3.7 Лексический канал не знает русского

`table.create_fts_index("text", replace=True)` — токенайзер по умолчанию,
без стемминга. «вентиляции» не найдёт «вентиляция». У LES свой стеммер
(`stem_russian_word`), стоп-слова, и построитель FTS-запроса, который стеммы
превращает в префиксные термы `"вентиляц"*`, шифры норм оставляет в кавычках,
а поиск терминов ограничивает колонкой `text` (чтобы имена файлов не тянули
короткие таблицы наверх).

### 3.8 Прочее

* `validator/crag.py` — на неё ссылаются только тесты, в проде мёртвая (наш же roadmap это отмечает).
* В `vector_store._build_where` остались персональные подстроки путей
  (`Downloaded_GOSTs`, `Parsing`, `#_Work`, `ПД_PDF`), которые OR-ом расширяют
  dataset-фильтр за пределы `config.yaml`. Это тихая утечка scope.
* Векторы хранятся во `float16` — экономия памяти ценой точности, нигде не измерена.
* 24 тестовых файла против 372 у LES; нет разделения «syntax gate / rag-core gate / full».

## 4. Что берём — по волнам

Каждый пункт помечен: **NR** = не требует переиндексации, **RI** = требует.

### Волна 0 — честность контура (NR, дёшево, высокий эффект)

1. **Контракт эмбеддингов.** Сверять `data["model"]` из ответа Lemonade
   с `config.embedder.model` (нормализованно, в обе стороны). Писать
   `data/index_manifest.json` рядом с LanceDB: модель, размерность, чанкер,
   версия схемы. При расхождении — `search_documents` возвращает явный
   `blocked` с `error_code=embedding_contract_mismatch`, а не тихо ищет.
   Источник: `backend/interface.EmbeddingContractError`,
   `docs/superpowers/specs/2026-07-17-llama-cpp-embedding-contract-design.md`.

2. **Честный retrieval trace.** Добавить в `debug` поля
   `channels` (`["dense"]` / `["dense","fts"]`), `fusion` (`none`/`linear`/`rrf`),
   `score_kind` (`dense_similarity`/`rrf`/`rerank_logit`), `status`, `error_code`.
   Гибрид упал → `status=degraded`, `fusion=none`, и это видно.
   Источник: `proxy/services/lexical_index_service.RetrievalTrace`.

3. **Контракт реранка.** В трейс `rerank: {status, model, pool_count,
   candidate_limit, input_count, returned_count}` + факт изменения головы списка.
   Сейчас при падении реранкера мы возвращаем `chunks[:top_k]` без единого сигнала.
   Источник: `retrieval_service.py:1003`, правило 6b в `ALGO-rag-best-practices.md`.

4. **OCR fail-closed.** `OCRProcessingError(code, page=N)` вместо строки-заглушки;
   per-page решение «есть текстовый слой» вместо per-document; порог
   `chars/page < 20 → OCR`; снять или сделать явным `VISION_MAX_PAGES`
   с записью «страницы 6..200 не распознаны» в статус файла.
   Источник: `codex/required-ocr` (`backend/ocr_parser.py`, `backend/converter.py`).

### Волна 1 — качество поиска (NR)

5. **RRF вместо линейной комбинации между dense и FTS.** У нас уже есть
   `fuse_ranked_results` — применить его к двум каналам вместо
   `LinearCombinationReranker(weight=alpha)`. Правило LES: несопоставимые шкалы
   не смешивают весами. `alpha` остаётся только для обратной совместимости API.

6. **Русский стемминг в лексическом канале.** Минимальный шаг — передать
   в `create_fts_index` русский токенайзер со стеммингом. Полный —
   перенести `stem_russian_word` + `NO_STEM_WORDS` + `build_fts_query`
   (префиксные стеммы, шифры в кавычках, поиск только по колонке `text`).
   Ожидаемый эффект по recall самый большой из всей волны.
   Источник: `proxy/services/lexical_index_service.py:144-216`.

7. **Exact-guards поверх выдачи.** Две функции, обе только переупорядочивают
   уже найденное, ничего не добавляют:
   * `_promote_explicit_norm_reference_matches` — если пользователь назвал
     «СП 7.13130», сам файл нормы важнее документов, которые на неё ссылаются;
   * `_promote_exact_identifier_matches` — дефисные обозначения (`ОВ-2`)
     держатся выше семантических соседей.
   Это общая замена нашему частному хаку `_PROJECT_FOLDER_MARKERS` в `crag.py`.
   Источник: `retrieval_service.py:170-248`.

8. **Калибровка по `score_kind`.** Пороги 0.55/0.35 в `crag.grade_retrieval`
   применять только когда `score_kind == "dense_similarity"`. Иначе — покрытие
   терминов запроса + разнообразие источников, как в
   `retrieval_quality_service.evaluate_retrieval_quality`.

9. **Очистка eval от контаминации.** Убрать доменные утверждения из
   `plan_query`/`_RETRY_AUGMENT` (расширения оставить, но выводимые из запроса);
   переписать golden в формате LES: `source_any`, `source_top_any`,
   `must_find` ищется только в тексте чанка и по умолчанию в одном чанке,
   плюс `min_top_score`. Получить честный baseline заново.
   Источник: `tools/rag_golden_set.py`, `docs/RAG_TEST_PROGRAM_AUDIT.md`.

### Волна 2 — доказуемость (частично RI)

10. **Страница как локатор.** В проекции PDF ставить маркеры `## Page N`,
    парсить их при чанкинге в `metadata["page"]`, добавить колонку в LanceDB.
    Даёт цитату «файл, стр. N». Требует переиндексации PDF-корпуса, но не
    смены эмбеддера. Источник: `backend/converter._parse_pdf_fast_text_layer`,
    `backend/provenance.ProvenanceLocator`.

11. **Layout-aware PDF.** `backend/pdf_layout.py` (254 строки): кластеризация
    блоков по X (колонки) → чтение сверху вниз внутри колонки → `find_tables()`
    → markdown pipe-таблицы, регион таблицы вырезается из текстового потока.
    Лечит «змейку» на двухколоночных СП. За флагом, с тихим фолбэком.
    Источник: `backend/pdf_layout.py`, `docs/ALGO-pdf-layout.md`.

12. **Подъём табличных приложений.** `table_appendix_service` (193 строки):
    распознавание таблицы по плотности `|`, добор top-N табличных чанков в пул
    при «табличном» интенте, и гарантия N слотов в видимом окне после реранка —
    иначе cross-encoder топит сырой текст таблицы под прозой. Работает в паре с (11).
    Источник: `proxy/services/table_appendix_service.py`, ADR-12 §Ц9.

13. **Evidence packet как формат ответа MCP.** `les.evidence_packet.v1`:
    `sources` (только реальные фрагменты, с локатором и `S1`/`Источник 1`),
    `navigation` (`context_role=navigation`, `is_evidence=false`),
    `deterministic_evidence`, `retrieval` (краткая диагностика), `missing`.
    Для MCP-сервера это естественнее плоского списка: клиент видит, что доказательство,
    что навигация, и чего не хватает. Источник: `proxy/services/evidence_packet_service.py`,
    `docs/ALGO-evidence-packet.md`.

### Волна 3 — архитектура (RI, отдельное окно)

14. **Hierarchy v1.** `backend/rag_hierarchy.py` — 140 строк, доменно-нейтральный,
    переносится почти как есть: детерминированные `node_id`, `ancestor_ids`,
    роли `evidence`/`navigation`, `evidence_only()` перед реранком и цитированием,
    RRF по нескольким «ногам». Даёт нам возможность класть в индекс карты
    и оглавления, не путая их с доказательствами.

15. **doc_router (ADR-12, стадия 1).** LLM выбирает документы-узлы по каталогу
    «шифр + область применения», результат валидируется по каталогу
    (анти-галлюцинация) и кэшируется в SQLite — доля LLM-вызовов стремится к нулю.
    Решает словарный разрыв, который поверхностный поиск не мостит:
    их кейс — «серверная» буквально сидит в СП про суды и тюрьмы, а регулируют
    её СП 485/486 через категорию «помещения с ЭВМ». У нас та же болезнь.
    Важная деталь: карточка документа строится из раздела «Область применения»
    по `section_heading`, **а не из `chunk_ord=0`** — иначе попадаешь в глоссарий.
    Источник: `proxy/services/doc_router.py`, `docs/ADR-12-typed-retrieval.md`.

16. **Штамп чертежа (ГОСТ Р 21.101).** `title_block_extract_service` (271 строка):
    заголовок чертежа — не вверху страницы, а в основной надписи справа внизу.
    Дополняет наш ColPali-контур метаданными листа.

17. **Манифест/аттестация индекса.** Лёгкий аналог `les.rag.index-contract.v2`:
    оффлайн-скрипт проходит LanceDB и подтверждает, что все точки собраны одной
    моделью, одним чанкером, с непустыми локаторами. Источник:
    `backend/index_contract_attestation.py` (536 строк — брать идею, не объём).

### Волна 4 — дисциплина

18. **Разделить гейты.** `make verify` (синтаксис/импорт/сбор тестов — не проверка
    поведения) отдельно от `make test-rag-core` (обязательный offline-инвариант ядра)
    и полной сюиты. У LES `RAG_CORE_TESTS` — 13 файлов, включён в `ship-check`.

19. **Живой golden-харнесс.** `tools/rag_golden_set.py` с флагами
    `--require-source-verification`, `--require-native-rrf`: каждый кейс требует
    `retrieval_trace.status=ok`, `fusion=rrf`, и проверяемый источник.

20. **Документация как код.** `MODULE_INDEX` со статусом «док ↔ код»,
    один `ALGO-*` на алгоритм, `RELEASE_LEDGER` вместо датированных саммари.
    Правило LES: «док не должен врать о коде; при расхождении прав КОД».

## 5. Что сознательно НЕ берём

* **Компаунд гейтов.** Собственный аудит LES (`docs/AUDIT_RAG_ARCHITECTURE.md`)
  показал: ядро корректно, но пять quality-гейтов и три роутера над ним
  не аддитивны и валят элементарный запрос («требования к шумоглушению»
  при трёх верных СП в выдаче → отказ). Мы сейчас легче — это преимущество.
  Берём их **принцип исправления**, а не их слоёный пирог:
  > Нашли релевантные чанки → синтезировали ответ с цитатами. Это должно работать
  > всегда. Всё остальное аддитивно: улучшает, но никогда не зануляет.

* **Qdrant-native RRF и BGE-M3 learned sparse.** Требуют Qdrant; у нас LanceDB.
  Из `backend/inference/bm25_sparse.py` берём только идею лёгкого лексического
  канала на стеммах вместо нейросетевого sparse (у них BGE-M3 занимал ~9 часов
  на 169k чанков, поэтому они от него и ушли).

* **Прокси на 184 сервиса, Sovushka UI, сметы, RIM, почта, нормоконтроль, MLX-хост.**
  Вне области MCP-сервера.

* **Immutable-аттестация с generation id, alias swap, token revocation.**
  Это решение для многопользовательского рантайма с внешними писателями.
  У нас single-writer — достаточно манифеста и оффлайн-проверки.

## 6. Предлагаемый порядок

Волна 0 целиком (1-4) — это неделя работы и снимает класс «тихих» отказов,
которые сейчас невозможно диагностировать. Волна 1 (5-9) — основной прирост
качества поиска, тоже без переиндексации, но её нельзя мерить старым eval,
поэтому пункт 9 идёт первым внутри волны. Волны 2-3 планируются под окно
переиндексации, вместе с уже отложенными идеями из `RAG_NOREINDEX_PLAN.md`
(contextual retrieval, late chunking, более тяжёлый эмбеддер).
