# FlyingRAG — Текущий статус проекта (LATEST)

**Актуальный этап**: Stage 4.2.8 — AUTO-START-01 EVIDENCE CLOSURE (ТЗ `FR-TZ-20261117-010` / Редакция 1.1 от 2026-11-17, SHA-256 `b8aad4dbed91627abb5cdff239f1b1067e440b31eeae2df3f0590c44ceb1f664`, 15,079 байт)  
**Статус документа**: **CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: BLOCKED_SETUP_REQUIRED (GO_PENDING_LIVE_CYCLE) / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED**  
**Принятый код (tested code commit Phase A)**: [`9b95161eaf8bfe7b512babc9dacc8d3c19cbc5d4`](https://github.com/Kritik35/flying-rag-mcp/commit/9b95161eaf8bfe7b512babc9dacc8d3c19cbc5d4)  
**Tree SHA кода**: `dce08a118d1ca1dac28c1082b3de9531bc5b2f20`  
**Предыдущий отчётный коммит (preceding reports HEAD)**: [`2bc75d4ac1e81fd2b13916116818c7ee85c09695`](https://github.com/Kritik35/flying-rag-mcp/commit/2bc75d4ac1e81fd2b13916116818c7ee85c09695) (Tree: `325fe51dd8c532f305c7cf64b04d0fe2d0bdc417`)  
**Предыдущий коммит кода (prior tested code anchor)**: [`dcf98d5039808b01462b420993feba48ac600cfe`](https://github.com/Kritik35/flying-rag-mcp/commit/dcf98d5039808b01462b420993feba48ac600cfe) (Tree: `dc7ca2772f80e033bac20d1485bb26faf2eb09ed`)  
**Исходный базовый коммит (baseline anchor)**: `9b498bf5dc09e964d035049a53582d52f13cdc95` (ветка `integration/acer-qwen-embedding`, чистый)  
**Боевая база данных**: `C:/RAG_Acer/data_imported/metadata.db` (размер: 1,485,103,104 байт, WAL: 0 байт, строго READ-ONLY)  
**Реальные поисковые вызовы к корпусу**: **СТРОГО 0** (`actual_search_calls_executed = 0`)  
**Текущий операционный статус**: **`CONTRACT_GATE_READY: GO / AUTOSTART_CODE_GATE: GO / AUTOSTART_READY: BLOCKED_SETUP_REQUIRED / AUTOSTART_MODE: AUTO_EXECUTE_SCOPED / LIVE_GATE: NOT_EXECUTED / SESSION_RESTART_RECOVERY: CONFIGURED_UNOBSERVED / WINDOWS_POWER_RECOVERY: CONFIGURED_UNOBSERVED / SNAPSHOT_READY: NO_GO / REAL_CORPUS_PILOT: NOT_EXECUTED / PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`**  
**Режим**: STRICT OFFLINE / ISOLATED DEVELOPMENT / PRODUCTION READ-ONLY / NO REINDEX / NO FORCE PUSH  

---

## 1. Официальные вердикты гейтов

| Проверяемое направление | Вердикт | Обоснование |
|:---|:---:|:---|
| **`CONTRACT_GATE_READY`** | **`GO`** | 70/70 контрактных тестов пройдены (40 базовых + 10 NG + 10 G2 + 10 G3). Численная конечность, канонический манифест 80/25 и безопасность подтверждены. |
| **`AUTOSTART_CODE_GATE`** | **`GO`** | Устранены замечания ТЗ-010 Редакции 1.1: строгое отслеживание последовательности и уникальности `call_id` без позиционной привязки (Scenarios A1..A3); запрет пересечения каталогов артефактов между задачами и попытками (Cross-Job Isolation, Foreign Temp Rejection, C4-05). 122/122 тестов успешно пройдены. |
| **`AUTOSTART_READY`** | **`BLOCKED_SETUP_REQUIRED`** | **Честный статус хоста**: на хосте Acer (`almax`) отсутствует подтверждённая ОС-изоляция (AppContainer/Docker sandbox token). Диспетчер надёжно удерживает задачу до авторизации среды оператором. |
| **`AUTOSTART_MODE`** | **`AUTO_EXECUTE_SCOPED`** | Активирован в конфигурации; строго ограничен верификацией границ. |
| **`LIVE_GATE`** | **`NOT_EXECUTED`** | На хосте Acer действует операторский стоп-маркер `watcher.pause`. Принудительный обход паузы запрещён регламентом. |
| **`SESSION_RESTART_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Схема v2, durable intent и обработка сбоев настроены в коде; статус зафиксирован контрактными тестами, реальный непредвиденный сбой daemon не симулировался. |
| **`WINDOWS_POWER_RECOVERY`** | **`CONFIGURED_UNOBSERVED`** | Параметр `StartWhenAvailable = true` включён в планировщике Windows; физический цикл сна/пробуждения оператором непосредственно не наблюдался. |
| **`SNAPSHOT_READY`** | **`NO_GO`** | Изолированная копия боевой базы данных не создавалась. Боевая база данных `C:/RAG_Acer/data_imported/metadata.db` остаётся в режиме READ-ONLY (WAL: 0 байт, не изменялась). |
| **`MODEL_INDEX_IDENTITY`** | **`UNVERIFIED`** | Сервер эмбеддингов 8089 выключен. Живая проверка соответствия весов модели размерности боевого индекса LanceDB не выполнялась. |
| **`EMBEDDING_PROFILE`** | **`UNVERIFIED`** | Профиль совместимости модели с боевым индексом LanceDB не подтверждён живым прогоном. |
| **`REAL_CORPUS_PILOT`** | **`NOT_EXECUTED`** | К боевому корпусу выполнено ровно 0 поисковых вызовов (`actual_search_calls = 0`). Все тесты проведены на синтетических фикстурах в temp. |
| **`PRODUCTION_DEPLOYMENT`** | **`NOT_AUTHORIZED`** | Боевой репозиторий `C:/RAG_Acer/repos/flying-rag-mcp` остаётся строго на коммите `9b498bf5dc09e964d035049a53582d52f13cdc95`. |

---

## 2. Сводка результатов тестов (122 / 122 PASS)

1. **`tests/test_autostart_evidence_closure.py`**: **13 / 13 PASS**
   - Целевой пакет проверок C4-01 .. C4-10 + Scenarios A1..A3, Foreign Attempt, Cross-Job Isolation
2. **`tests/test_autostart_provenance_and_permissions.py`**: **9 / 9 PASS**
   - Целевой пакет проверок S3-01 .. S3-10
3. **`tests/test_autostart_dispatcher.py`**: **12 / 12 PASS**
   - Регрессионная матрица A4R-01 .. A4R-12
4. **`tests/test_drive_inbox_watcher.py`**: **18 / 18 PASS**
   - Базовые сценарии монитора Google Drive
5. **`tests/test_real_retrieval_shadow_pilot.py`**: **70 / 70 PASS**
   - Базовые контрактные тесты Stage 4.2.8: 40
   - Негативные контрактные тесты Revision 1 (NG-01..NG-10): 10
   - Негативные контрактные тесты Revision 2 (G2-01..G2-10): 10
   - Негативные контрактные тесты Revision 3 (G3-01..G3-10): 10
- **ИТОГО**: **122 / 122 PASS (100%)**

---

## 3. Проверенная цепочка коммитов

```
9b498bf (baseline anchor on integration/acer-qwen-embedding)
  └── ...
        └── c5cf3ae (reports HEAD for TZ-009)
              └── 12f15b5 (code commit Phase A for TZ-010)
                    └── dcf98d5 (refined code commit Phase A for TZ-010)
                          └── 2bc75d4 (reports HEAD for TZ-010 Rev 1.0)
                                └── 9b95161 (tested code commit Phase A for TZ-010 Rev 1.1)
                                      └── [HEAD] (reports commit Phase B for TZ-010 Rev 1.1)
```

---

## 4. Единственное необходимое действие оператора

Для перехода к живому выполнению автоматических задач (`AUTOSTART_READY: GO`):
1. **Настроить ОС-изоляцию среды исполнения** (Windows AppContainer или локальный Docker-контейнер).
2. **Сгенерировать файл `security_boundary.json`** с токеном аттестации и указанием изолированных рабочих каталогов.
3. **Снять маркер паузы** `watcher.pause` на станции Acer.
