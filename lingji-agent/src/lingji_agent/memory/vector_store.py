"""ChromaDB 本地向量存储 — Sprint 4 T-4.1"""

import logging
import os
from typing import Any, Literal

logger = logging.getLogger(__name__)

CollectionName = Literal["episodic", "semantic"]


def _default_embedding_function():
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    return ONNXMiniLM_L6_V2()


class LocalVectorStore:
    """ChromaDB 持久化向量库：情景记忆 + 语义记忆双 Collection"""

    def __init__(
        self,
        db_path: str,
        embedding_function=None,
    ):
        import chromadb

        expanded = os.path.expanduser(db_path)
        os.makedirs(expanded, exist_ok=True)

        self._embedder = embedding_function or _default_embedding_function()
        self.client = chromadb.PersistentClient(path=expanded)

        self.episodic_col = self.client.get_or_create_collection(
            name="episodic_memory",
            embedding_function=self._embedder,
            metadata={"hnsw:space": "cosine"},
        )
        self.semantic_col = self.client.get_or_create_collection(
            name="semantic_memory",
            embedding_function=self._embedder,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("vector_store_initialized path=%s", expanded)

    def _collection(self, collection_name: CollectionName):
        return self.episodic_col if collection_name == "episodic" else self.semantic_col

    def add_memory(
        self,
        collection_name: CollectionName,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        col = self._collection(collection_name)
        col.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )

    def search(
        self,
        collection_name: CollectionName,
        query: str,
        top_k: int = 3,
        *,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        col = self._collection(collection_name)
        if col.count() == 0:
            return []

        query_kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": min(top_k, col.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if metadata_filter:
            query_kwargs["where"] = metadata_filter

        results = col.query(**query_kwargs)

        memories: list[dict[str, Any]] = []
        if not results or not results.get("documents") or not results["documents"][0]:
            return memories

        for i, doc in enumerate(results["documents"][0]):
            distance = results["distances"][0][i] if results.get("distances") else 0.0
            memories.append({
                "content": doc,
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                "relevance_score": 1.0 - distance,
            })
        return memories

    def list_episodic_with_metadata(self) -> list[tuple[str, dict[str, Any]]]:
        """列出全部情景记忆 id 与 metadata（供 prune 使用）"""
        col = self.episodic_col
        if col.count() == 0:
            return []
        data = col.get(include=["metadatas"])
        ids = data.get("ids") or []
        metas = data.get("metadatas") or []
        return [(doc_id, meta or {}) for doc_id, meta in zip(ids, metas)]

    def delete_by_ids(self, collection_name: CollectionName, doc_ids: list[str]) -> None:
        if not doc_ids:
            return
        col = self._collection(collection_name)
        col.delete(ids=doc_ids)
        logger.info("deleted_memories collection=%s count=%d", collection_name, len(doc_ids))

    def count(self, collection_name: CollectionName) -> int:
        return self._collection(collection_name).count()

    def get_document(self, collection_name: CollectionName, doc_id: str) -> str | None:
        col = self._collection(collection_name)
        try:
            data = col.get(ids=[doc_id], include=["documents"])
        except Exception:
            return None
        docs = data.get("documents") or []
        if not docs or not docs[0]:
            return None
        return docs[0]
