"""Instrument type classification driven by ``config/instrument_types.yaml``."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from tmon.core.config import BACKEND_ROOT
from tmon.domain.enums import InstrumentType
from tmon.ingest.tsetmc.parsers import normalize_fa

DEFAULT_PATH = BACKEND_ROOT / "config" / "instrument_types.yaml"


@dataclass(frozen=True)
class Classifier:
    rules: tuple[tuple[InstrumentType, tuple[str, ...]], ...]
    default: InstrumentType
    tradable: frozenset[InstrumentType]

    def classify(
        self, *, group_title: str | None, name_fa: str | None
    ) -> tuple[InstrumentType, bool]:
        """Return ``(type, matched)``; ``matched`` is False when the default was used."""
        haystack = normalize_fa(" ".join(x for x in (group_title, name_fa) if x))
        for itype, keywords in self.rules:
            if any(normalize_fa(k) in haystack for k in keywords):
                return itype, True
        return self.default, False

    def is_tradable(self, itype: InstrumentType | str) -> bool:
        return InstrumentType(itype) in self.tradable


def load_classifier(path: Path = DEFAULT_PATH) -> Classifier:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = tuple((InstrumentType(r["type"]), tuple(r["keywords"])) for r in raw["rules"])
    return Classifier(
        rules=rules,
        default=InstrumentType(raw["default_type"]),
        tradable=frozenset(InstrumentType(t) for t in raw["tradable_types"]),
    )


@lru_cache
def get_classifier() -> Classifier:
    return load_classifier()
