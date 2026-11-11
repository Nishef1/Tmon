"""Instrument type classification driven by ``config/instrument_types.yaml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from tmon.core.config import BACKEND_ROOT
from tmon.domain.enums import InstrumentType
from tmon.ingest.tsetmc.parsers import normalize_fa

DEFAULT_PATH = BACKEND_ROOT / "config" / "instrument_types.yaml"
FUND_CODE = "fund"  # pseudo-type in ``type_codes``: resolved by the fund rules


def _squash(text: str) -> str:
    """Normalized text without spaces or ZWNJ: TSETMC writes both "درآمدثابت" and "درآمد ثابت"."""
    return normalize_fa(text).replace(" ", "").replace("‌", "")


@dataclass(frozen=True)
class Classifier:
    rules: tuple[tuple[InstrumentType, tuple[str, ...]], ...]
    default: InstrumentType
    tradable: frozenset[InstrumentType]
    recommendable: frozenset[InstrumentType]
    not_recommendable_groups: tuple[str, ...]
    derivatives_board: str
    type_codes: dict[str, str] = field(default_factory=dict)
    fund_rules: tuple[tuple[InstrumentType, tuple[str, ...]], ...] = ()
    fund_name_suffixes: tuple[tuple[str, InstrumentType], ...] = ()

    def classify(
        self,
        *,
        group_title: str | None,
        name_fa: str | None,
        board: str | None = None,
        type_code: str | None = None,
        fund_desc: str | None = None,
    ) -> tuple[InstrumentType, bool]:
        """Return ``(type, matched)``; ``matched`` is False when the default was used.

        ``type_code`` is TSETMC's own type code (``yVal``): a listed code decides, and funds
        take their subtype from ``fund_desc`` (``faraDesc``) and then the name. Otherwise the
        keyword rules apply. ``board`` is the market the instrument trades in (``flowTitle``):
        anything that no rule names but trades on the derivatives board is a future."""
        code = self.type_codes.get(type_code.strip()) if type_code else None
        if code == FUND_CODE:
            return self._fund_type(fund_desc, name_fa)
        if code is not None:
            return InstrumentType(code), True
        haystack = normalize_fa(" ".join(x for x in (group_title, name_fa) if x))
        for itype, keywords in self.rules:
            if any(normalize_fa(k) in haystack for k in keywords):
                return itype, True
        if board and normalize_fa(self.derivatives_board) in normalize_fa(board):
            return InstrumentType.FUTURE, True
        return self.default, False

    def _fund_type(self, desc: str | None, name: str | None) -> tuple[InstrumentType, bool]:
        for text in (desc, name):
            t = _squash(text or "")
            for itype, keywords in self.fund_rules:
                if t and any(_squash(k) in t for k in keywords):
                    return itype, True
        n = _squash(name or "")
        for suffix, itype in self.fund_name_suffixes:
            if n.endswith(_squash(suffix)):
                return itype, True
        return InstrumentType.OTHER, False

    def is_tradable(self, itype: InstrumentType | str) -> bool:
        """Ingested and kept (history, comparison page): a superset of the recommendable set."""
        return InstrumentType(itype) in self.tradable

    def is_recommendable(
        self, itype: InstrumentType | str, *, board: str | None, group_title: str | None
    ) -> bool:
        """The phase-1 recommendation universe (ADR 0002 section 1): stocks on the exchange,
        the first and second Fara Bourse markets and the yellow base market, equity and mixed
        ETFs. Orange and red base markets, rights, bonds, other funds and derivatives are out."""
        if InstrumentType(itype) not in self.recommendable:
            return False
        if board and normalize_fa(self.derivatives_board) in normalize_fa(board):
            return False
        g = normalize_fa(group_title or "")
        return not any(normalize_fa(x) in g for x in self.not_recommendable_groups)


def load_classifier(path: Path = DEFAULT_PATH) -> Classifier:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = tuple((InstrumentType(r["type"]), tuple(r["keywords"])) for r in raw["rules"])
    return Classifier(
        rules=rules,
        default=InstrumentType(raw["default_type"]),
        tradable=frozenset(InstrumentType(t) for t in raw["tradable_types"]),
        recommendable=frozenset(InstrumentType(t) for t in raw["recommendable_types"]),
        not_recommendable_groups=tuple(raw["not_recommendable_groups"]),
        derivatives_board=raw["derivatives_board"],
        type_codes={str(k): str(v) for k, v in (raw.get("type_codes") or {}).items()},
        fund_rules=tuple(
            (InstrumentType(r["type"]), tuple(r["keywords"])) for r in raw.get("fund_rules") or ()
        ),
        fund_name_suffixes=tuple(
            (str(k), InstrumentType(v)) for k, v in (raw.get("fund_name_suffixes") or {}).items()
        ),
    )


@lru_cache
def get_classifier() -> Classifier:
    return load_classifier()
