import os
import yaml
import logging
from typing import Optional, List, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)

class LesQdrantBridge:
    def __init__(self, config_path: str = "config.yaml"):
        self.url = "http://127.0.0.1:6333"
        self.collection_name = "les_rag"
        self.enabled = False
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                if "les_integration" in cfg:
                    self.enabled = cfg["les_integration"].get("enabled", False)
                    self.url = cfg["les_integration"].get("qdrant_url", self.url)
                    self.collection_name = cfg["les_integration"].get("collection_name", self.collection_name)
        except Exception as e:
            logger.warning(f"Failed to load config for Qdrant bridge: {e}")
            
        if self.enabled:
            # Bypass system proxies for local Qdrant connections
            import os
            os.environ["NO_PROXY"] = "*"
            for p in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
                if p in os.environ:
                    del os.environ[p]
            # We use check_compatibility=False as done in Les
            self.client = QdrantClient(url=self.url, timeout=10.0, check_compatibility=False)
        else:
            self.client = None

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        folder_filter: Optional[str] = None,
        dataset: Optional[str] = None,
    ) -> list[dict]:
        if not self.enabled or not self.client:
            return []
            
        must = []
        if dataset:
            # In Les, dataset_id is typically what dataset corresponds to
            must.append(models.FieldCondition(key="dataset_id", match=models.MatchValue(value=dataset)))
            
        if folder_filter:
            # folder_filter in Flying Rag maps to path. In Les, we only have file_name.
            must.append(models.FieldCondition(key="file_name", match=models.MatchText(text=folder_filter)))
            
        query_filter = models.Filter(must=must) if must else None
        
        try:
            # Try unnamed vector first
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True
            ).points
        except Exception as e:
            if "vector name" in str(e).lower() or "not found" in str(e).lower():
                # Try named vector "text"
                try:
                    results = self.client.query_points(
                        collection_name=self.collection_name,
                        query=("text", query_embedding),
                        query_filter=query_filter,
                        limit=top_k,
                        with_payload=True
                    ).points
                except Exception as inner_e:
                    logger.error(f"Les Qdrant bridge search failed with named vector: {inner_e}")
                    return []
            else:
                logger.error(f"Les Qdrant bridge search failed: {e}")
                return []

        formatted_results = []
        for p in results:
            text = p.payload.get("text", "")
            doc_id = p.payload.get("doc_id", "")
            file_name = p.payload.get("file_name", "")
            chunk_id = str(p.id)
            
            formatted_results.append({
                "chunk_id": chunk_id,
                "parent_id": chunk_id, # No parent_id in Les
                "doc_id": doc_id,
                "text": text,
                "child_text": text,
                "context_source": "les_qdrant",
                "context_chars": len(text),
                "source_path": file_name, # Map file_name to source_path for Flying RAG compatibility
                "file_name": file_name,
                "section": p.payload.get("dataset_id", ""), # Use dataset_id as section
                "score": round(p.score, 4),
            })
            
        return formatted_results
