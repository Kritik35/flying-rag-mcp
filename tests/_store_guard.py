"""Может ли тест писать в хранилище, на которое сейчас смотрит конфигурация.

`tests/test_comprehensive.py` выполняется при импорте, и при доступном Lemonade
его раздел 9 индексировал временный файл в хранилище из корневого config.yaml —
то есть в боевое. Очистка после него промахивалась, и в рабочем LanceDB
накопилось 90 фрагментов «ГОСТ Р 12345-2026 Тестовый документ» от 18 прогонов:
поддельный норматив, который мог всплыть в нормативном поиске.

Правило простое: писать можно только туда, куда явно направил
`FLYING_RAG_CONFIG` — так делает `scripts/verify_local.py`, поднимая временное
хранилище. Без переменной конфигурация боевая, и тест обязан только читать.
"""
from __future__ import annotations

import os
from pathlib import Path


def live_config_paths() -> set[Path]:
    """Где может лежать боевой конфиг: у кода и в доме оператора."""
    import config_loader
    return {(config_loader.ROOT / config_loader.DEFAULT_NAME).resolve(),
            (config_loader.home() / config_loader.DEFAULT_NAME).resolve()}


def writes_allowed() -> bool:
    """True, только если конфигурация явно уведена с боевой."""
    import config_loader

    if not os.getenv(config_loader.CONFIG_ENV, "").strip():
        return False
    return config_loader.config_path().resolve() not in live_config_paths()
