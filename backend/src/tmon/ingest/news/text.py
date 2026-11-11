"""Persian normalisation (docs/08 step 2) and near-duplicate detection (step 3)."""

from __future__ import annotations

import re
from functools import lru_cache

from tmon.ingest.codal.parsers import ascii_digits

_WORD = re.compile(r"\w+")
# share of 3-word shingles two titles must have in common to be the same story
DUPLICATE_JACCARD = 0.5


@lru_cache(maxsize=1)
def _normalizer():  # type: ignore[no-untyped-def]
    from hazm import Normalizer

    return Normalizer()


def normalize(text: str) -> str:
    """Arabic ye/kaf, half-spaces and spacing via hazm, then Persian digits to ASCII."""
    return ascii_digits(_normalizer().normalize(text)).strip()


def shingles(text: str, k: int = 3) -> frozenset[str]:
    words = _WORD.findall(text.replace("‌", " "))
    if len(words) < k:
        return frozenset([" ".join(words)]) if words else frozenset()
    return frozenset(" ".join(words[i : i + k]) for i in range(len(words) - k + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
