from __future__ import annotations

import hashlib
from collections.abc import Mapping

from redis.asyncio import Redis


def fingerprint(service: str, labels: Mapping[str, str]) -> str:
    """
    Deterministic fingerprint based on service + sorted labels.

    Algorithm:
      - Sort labels by key
      - Canonicalize as: `service=<service>;k1=v1,k2=v2,...`
      - SHA256 over UTF-8 bytes
    """

    canonical_labels = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    canonical = f"service={service};labels={canonical_labels}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def dedupe_hit(
    *,
    redis: Redis,
    alert_fingerprint: str,
    window_seconds: int = 300,
) -> bool:
    """
    Returns True if this fingerprint was seen within the dedupe window.

    Implementation:
      - SET key NX with EX window
      - If SET fails => dedupe hit
    """

    dedupe_key = f"alerts:dedupe:{alert_fingerprint}"
    was_set = await redis.set(dedupe_key, "1", ex=window_seconds, nx=True)
    return was_set is None or was_set is False

