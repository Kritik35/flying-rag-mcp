# FlyingRAG Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть подтверждённые риски безопасности и потери данных без обращения к рабочим датасетам.

**Architecture:** Защитные проверки добавляются на существующих границах MCP, watcher, backfill и HTTP/cache. Форматы индекса и retrieval pipeline не меняются.

**Tech Stack:** Python 3.12/3.13, unittest, SQLite, MCP, LanceDB boundary mocks.

## Global Constraints

- Никаких чтений или записей рабочих LanceDB, metadata.db, engineering_rules и semantic cache.
- Все write-тесты используют TemporaryDirectory и временные SQLite-файлы.
- Никакого reindex, watcher, indexer или backfill на рабочем корпусе.
- Сохранить embeddings, chunking, retrieval ranking и форматы индекса без изменений.
- Работать TDD: новый regression-тест обязан сначала упасть по ожидаемой причине.

---

### Task 1: Allowlist для reindex_path

**Files:**
- Modify: `rag_server/tools.py`
- Test: `test_production_readiness.py`

- [ ] Добавить failing-тесты для пути вне watched folder, traversal и разрешённого descendant.
- [ ] Запустить targeted-тест и подтвердить RED.
- [ ] Реализовать каноническую allowlist-проверку до `Popen`.
- [ ] Запустить targeted-тест и подтвердить GREEN.

### Task 2: Последовательный watcher writer

**Files:**
- Modify: `main.py`
- Test: `test_watcher_serialization.py`

- [ ] Добавить failing-тест на отсутствие двух одновременно работающих indexer subprocess.
- [ ] Добавить failing-тест на coalescing повторных событий одного пути.
- [ ] Подтвердить RED.
- [ ] Выделить тестируемый последовательный worker с bounded/coalescing queue.
- [ ] Подтвердить GREEN без запуска реального indexer.

### Task 3: Атомарный rules backfill

**Files:**
- Modify: `backfill_rules.py`
- Modify: `storage/metadata_db.py`
- Test: `test_backfill_rules_atomicity.py`

- [ ] Создать временную SQLite с существующим правилом и failing-тест provider failure.
- [ ] Проверить, что текущий код удаляет правило или ложно сообщает успех.
- [ ] Реализовать transactional replacement после полного извлечения.
- [ ] Добавить статусы success, partial и failed.
- [ ] Подтвердить rollback и GREEN.

### Task 4: Proxy scope, cache generation, MCP redaction и logging

**Files:**
- Modify: `embedder/client.py`
- Modify: `storage/rules_extractor.py`
- Modify: `storage/semantic_cache.py`
- Modify: `rag_server/tools.py`
- Modify: `rag_server/server.py`
- Modify: `backfill_rules.py`
- Test: `test_runtime_hardening.py`

- [ ] Добавить failing-тест, что imports/constructors не меняют NO_PROXY.
- [ ] Добавить failing-тест cache scope generation.
- [ ] Добавить failing-тест на отсутствие абсолютного пути в MCP error/result.
- [ ] Добавить failing-тест bounded logging configuration.
- [ ] Реализовать минимальные изменения и подтвердить GREEN.

### Task 5: Полная проверка

**Files:**
- Modify: `docs/superpowers/plans/2026-07-11-flyingrag-hardening.md` только для отметок исполнения при необходимости.

- [ ] Запустить py_compile из AGENTS.md.
- [ ] Запустить базовый unittest-набор из AGENTS.md.
- [ ] Запустить все новые targeted-тесты.
- [ ] Запустить `git diff --check`.
- [ ] Проверить diff на обращения к runtime путям и destructive операции.
- [ ] Провести независимый полный code review ветки.
