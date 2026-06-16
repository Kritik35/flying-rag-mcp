from __future__ import annotations
from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """
    Абстрактный интерфейс для провайдеров векторных представлений (эмбеддингов).
    Позволяет бесшовно заменять локальные и облачные инференс-движки.
    """

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Получить эмбеддинги для списка текстов.
        Возвращает список векторов (каждый вектор - list[float]).
        """
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """Вернуть размерность вектора (например, 1024)."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Вернуть название модели."""
        pass

    @abstractmethod
    def check_connection(self) -> bool:
        """Проверить доступность сервиса. True если OK."""
        pass
