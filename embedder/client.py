from __future__ import annotations
import os
import httpx
from urllib.parse import urlparse
import yaml
from pathlib import Path
from embedder.abstract import EmbeddingProvider
from embedder.contract import EmbeddingContractError, check_response_model

LEMONADE_URL = "http://localhost:13305/api/v1/embeddings"
MODEL = "Qwen3-Embedding-0.6B-GGUF"
TIMEOUT = 30.0
MAX_RETRIES = 3


def _httpx_client_kwargs(url: str) -> dict:
    """Bypass environment proxies only for loopback requests, without mutation."""
    host = (urlparse(url).hostname or "").lower()
    return {"trust_env": False} if host in {"localhost", "127.0.0.1", "::1"} else {}


def load_config():
    from config_loader import load_config as _load
    return _load()


class LemonadeEmbeddingProvider(EmbeddingProvider):
    def __init__(self) -> None:
        config = load_config()
        lemonade_cfg = config.get("lemonade", {})
        emb_cfg = config.get("embedder", {})

        base_url = emb_cfg.get("base_url", lemonade_cfg.get("base_url", ""))
        default_url = f"{base_url.rstrip('/')}/embeddings" if base_url else LEMONADE_URL

        self.url = emb_cfg.get("url", lemonade_cfg.get("url", default_url))
        self.model = emb_cfg.get("model", lemonade_cfg.get("model", MODEL))
        self.timeout = float(emb_cfg.get("timeout_sec", lemonade_cfg.get("timeout_sec", TIMEOUT)))
        # A server that omits the model field cannot be verified. Default is to
        # record that as `unverified` rather than block; set
        # embedder.require_model_report: true to fail closed instead.
        self.require_model_report = bool(
            emb_cfg.get("require_model_report", lemonade_cfg.get("require_model_report", False))
        )
        self._dimension: int | None = None
        self._actual_model: str = ""
        self._contract_status: str = "unchecked"
        self._contract_detail: str = ""

    def prepare_texts(self, texts: list[str], is_query: bool = False) -> list[str]:
        processed_texts = []
        for text in texts:
            if is_query and "bge-m3" in self.model.lower():
                processed_texts.append(f"Represent this query for retrieving relevant documents: {text}")
            elif is_query and "qwen3-embedding" in self.model.lower():
                processed_texts.append(
                    "Instruct: Given a Russian or English engineering search query, "
                    "retrieve relevant passages from standards, regulations, project "
                    f"documentation, tables, and technical notes.\nQuery: {text}"
                )
            else:
                processed_texts.append(text)
        return processed_texts

    def embed_batch(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        processed_texts = self.prepare_texts(texts, is_query=is_query)

        payload = {"model": self.model, "input": processed_texts}
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                strict_timeout = httpx.Timeout(self.timeout, connect=10.0, read=self.timeout)
                with httpx.Client(timeout=strict_timeout, **_httpx_client_kwargs(self.url)) as client:
                    resp = client.post(self.url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                if "error" in data:
                    raise RuntimeError(f"Lemonade: {data['error']}")
                # The model we asked for does not select the model on the server.
                # Verify what it actually ran before trusting these vectors.
                status, detail = check_response_model(
                    self.model, data.get("model"),
                    require_report=self.require_model_report,
                )
                self._contract_status = status
                self._contract_detail = detail
                if status == "ok":
                    self._actual_model = detail
                items = data["data"]
                items_sorted = sorted(items, key=lambda x: x["index"])
                vectors = [item["embedding"] for item in items_sorted]
                if vectors and self._dimension is None:
                    self._dimension = len(vectors[0])
                return vectors
            except httpx.HTTPError as exc:
                last_err = exc
                continue
        raise RuntimeError(
            f"Failed to get embeddings after {MAX_RETRIES} attempts: {last_err}"
        )

    def get_dimension(self) -> int:
        if self._dimension is not None:
            return self._dimension
        try:
            dummy_vec = self.embed_batch(["test_dim"])
            self._dimension = len(dummy_vec[0])
            return self._dimension
        except Exception:
            return 1024

    def get_model_name(self) -> str:
        return self.model

    def get_actual_model_name(self) -> str:
        """Model the server reported on the last successful call ('' if never verified)."""
        return self._actual_model

    def contract_state(self) -> dict:
        """Last embedding-contract verdict, for the retrieval trace."""
        return {
            "expected_model": self.model,
            "actual_model": self._actual_model,
            "status": self._contract_status,
            "detail": self._contract_detail,
        }

    def verify_contract(self) -> dict:
        """Force one round-trip so the contract state is populated.

        Raises :class:`EmbeddingContractError` when the server runs a different
        model than this index was built with.
        """
        if self._contract_status == "unchecked":
            self.embed_batch(["contract check"])
        return self.contract_state()

    def check_connection(self) -> bool:
        try:
            with httpx.Client(timeout=self.timeout, **_httpx_client_kwargs(self.url)) as client:
                resp = client.post(self.url, json={"model": self.model, "input": ["test"]})
                resp.raise_for_status()
                data = resp.json()
            items = data.get("data", [])
            return len(items) == 1 and isinstance(items[0].get("embedding"), list)
        except Exception:
            return False


_DEFAULT_PROVIDER = LemonadeEmbeddingProvider()


def get_embeddings(texts: list[str], is_query: bool = False) -> list[list[float]]:
    return _DEFAULT_PROVIDER.embed_batch(texts, is_query=is_query)


def check_connection() -> bool:
    return _DEFAULT_PROVIDER.check_connection()


if __name__ == "__main__":
    print("Checking lemonade-server connection...")
    prov = LemonadeEmbeddingProvider()
    if prov.check_connection():
        vecs = prov.embed_batch(["test connection"])
        print(f"OK: got vectors with dimension: {prov.get_dimension()}")
    else:
        print("WARN: lemonade-server offline")
