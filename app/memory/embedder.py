"""
Embedding support for semantic memory retrieval.

Uses Ollama's /api/embeddings endpoint to generate local vector embeddings.
Fully optional — if no embedding_model is configured, all operations are no-ops
and the memory system degrades gracefully to lexical-only retrieval.

Only Ollama is supported (LM Studio and KoboldCPP lack a standard embeddings endpoint).
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Optional

log = logging.getLogger("rp_utility")


def embed_text(text: str, base_url: str, model: str) -> Optional[list[float]]:
    """
    Generate an embedding vector for the given text.

    Returns a list of floats (the embedding) or None on any failure.
    Never raises — callers can treat None as "no embedding available".
    """
    if not model or not base_url:
        return None
    try:
        import urllib.request
        import json as _json

        url = base_url.rstrip("/") + "/api/embeddings"
        payload = _json.dumps({"model": model, "prompt": text}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
        vec = data.get("embedding")
        if not vec or not isinstance(vec, list):
            return None
        return [float(v) for v in vec]
    except Exception as exc:
        log.debug("Embedding failed (non-fatal): %s", exc)
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Cosine similarity between two vectors.
    Returns 0.0 if either vector is empty or zero-magnitude.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def encode_embedding(vec: list[float]) -> bytes:
    """Pack a float list into bytes for SQLite BLOB storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def decode_embedding(blob: bytes) -> list[float]:
    """Unpack bytes from SQLite BLOB back to a float list."""
    n = len(blob) // 4  # 4 bytes per float32
    return list(struct.unpack(f"{n}f", blob))
