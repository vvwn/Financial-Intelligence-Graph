"""Time-ordered UUID v7 generator.

Used for every primary key and request_id so that IDs sort by creation time
(helps cursor pagination and incident triage). Python 3.12 has no stdlib uuid7.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms: int = 0
_seq: int = 0


def uuid7() -> uuid.UUID:
    """Return a monotonic-ish UUIDv7.

    Layout: 48-bit unix ms | ver(4)=7 | 12-bit counter | var(2)=10 | 62-bit random.
    The 12-bit counter keeps ordering when several IDs are minted in the same ms.
    """
    global _last_ms, _seq

    with _lock:
        ms = int(time.time() * 1000)
        if ms == _last_ms:
            _seq = (_seq + 1) & 0xFFF
        else:
            _last_ms = ms
            _seq = 0
        seq = _seq

    value = (ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76
    value |= seq << 64
    value |= 0b10 << 62
    value |= int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def uuid7_str() -> str:
    return str(uuid7())


__all__ = ["uuid7", "uuid7_str"]
