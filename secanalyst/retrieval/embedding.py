"""Embedders: FastEmbedder (bge-small, ONNX, downloads the model once) and a deterministic
hashing FakeEmbedder for tests (no network)."""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def _norm(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(n == 0, 1.0, n)


class FastEmbedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> np.ndarray:
        return _norm(np.array(list(self.model.embed(texts, batch_size=32))))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([QUERY_PREFIX + text])[0]


class FakeEmbedder:
    """Bag-of-words hashing into ``dim`` buckets: deterministic, shares signal with BM25."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                h = int.from_bytes(hashlib.md5(w.encode()).digest()[:4], "little")
                out[i, h % self.dim] += 1.0
        return _norm(out)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]
