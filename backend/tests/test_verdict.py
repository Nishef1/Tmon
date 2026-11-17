"""ADR 0004 section 7: one test per row of the verdict table, for a non-holder and for a holder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tmon.api.routers.dashboard import final_verdict, verdict_fields
from tmon.core.engine_config import get_engine_config

COST = 0.017512
STUDY = Path(__file__).resolve().parents[2] / "docs" / "data" / "invested-study.json"
GRADES = {"ثابت‌شده": "proven", "احتمالی": "probable", "ثابت‌نشده": "unproven"}


def _doc(
    *, cand: str = "unproven", avoid: str = "unproven", exposure: float | None = 0.8
) -> dict[str, Any]:
    zone = {"deciles": [1], "net": 0.01, "net_h1": 0.005, "net_h2": 0.015, "t": 2.0, "grade": ""}
    return {
        "verdict": {
            "horizon_days": 60,
            "candidate_top_frac": 0.5,
            "avoid_bottom_frac": 0.4,
            "candidate_grade": cand,
            "avoid_grade": avoid,
        },
        "exposure": {"exposure": exposure},
        "round_trip_cost": COST,
        "evidence": [],
        "zones": {"60": {"days": 1000, "candidate": zone, "avoid": zone}},
    }


def _turning(state: str, mean: float = -0.01) -> dict[str, Any]:
    stat = {"n": 40000, "excess_mean": mean, "p_dn20": 0.1}
    return {
        "states": [],
        "symbols": {"7": {"state": state}},
        "history": {"states": {state: {"h60": stat}}, "base": {"h60": {"p_dn20": 0.1}}},
    }


def _entry(band: str | None, queue: str = "none") -> dict[str, Any]:
    return {"band": band, "queue_state": queue}


# --- non-holder column ----------------------------------------------------------------------


def test_candidate_buyable_is_a_candidate_with_its_grade_not_a_buy() -> None:
    v = final_verdict(_doc(), _entry("candidate"))
    assert v is not None
    assert (v.code, v.label, v.key, v.grade) == ("candidate", "نامزد خرید", "candidate", "unproven")
    assert not v.vetoed and not v.market_warning


def test_only_a_proven_candidate_zone_gives_buy() -> None:
    assert final_verdict(_doc(cand="probable"), _entry("candidate")).code == "candidate"  # type: ignore[union-attr]
    v = final_verdict(_doc(cand="proven"), _entry("candidate"))
    assert v is not None and (v.code, v.key, v.label) == ("buy", "buy", "خرید")


@pytest.mark.parametrize("grade", ["unproven", "probable", "proven"])
def test_candidate_in_a_buy_queue_is_never_buyable(grade: str) -> None:
    v = final_verdict(_doc(cand=grade), _entry("candidate", "buy_queue"))
    assert v is not None
    assert v.code == "candidate_queue" and v.key == "candidate" and "صف خرید" in v.headline
    assert v.code != "buy"


def test_candidate_with_a_state_veto_is_a_wait() -> None:
    v = final_verdict(_doc(cand="proven"), _entry("candidate"), _turning("hot"), 7)
    assert v is not None and v.code == "wait" and v.vetoed and v.key == "hold"
    assert v.label == "صبر" and "فعلاً نخرید" in v.headline
    # another symbol, or a state that beat the market: no veto
    assert final_verdict(_doc(), _entry("candidate"), _turning("hot"), 8).code == "candidate"  # type: ignore[union-attr]
    assert final_verdict(_doc(), _entry("candidate"), _turning("hot", 0.02), 7).code == "candidate"  # type: ignore[union-attr]


def test_middle_goes_with_the_market() -> None:
    v = final_verdict(_doc(), _entry("middle"))
    assert v is not None and (v.code, v.label, v.grade) == ("with_market", "همراه بازار", None)


@pytest.mark.parametrize("grade", ["probable", "proven"])
def test_avoid_with_backed_grade_is_avoid(grade: str) -> None:
    v = final_verdict(_doc(avoid=grade), _entry("avoid"))
    assert v is not None and (v.code, v.label, v.key) == ("avoid", "پرهیز", "sell")


def test_avoid_with_unproven_grade_goes_with_the_market() -> None:
    v = final_verdict(_doc(avoid="unproven"), _entry("avoid"))
    assert (
        v is not None and (v.code, v.key) == ("with_market", "hold") and "ثابت نشده" in v.headline
    )


def test_exposure_zero_says_wait_market_and_nobody_is_told_to_buy() -> None:
    for grade in ("unproven", "proven"):
        for queue in ("none", "buy_queue"):
            v = final_verdict(_doc(cand=grade, exposure=0.0), _entry("candidate", queue))
            assert v is not None and (v.code, v.label) == ("wait_market", "صبر: بازار")
            assert v.market_warning and v.key == "hold"
    mid = final_verdict(_doc(exposure=0.0), _entry("middle"))
    assert mid is not None and mid.code == "wait_market"
    low = final_verdict(_doc(exposure=0.0), _entry("avoid"))
    assert low is not None and low.code == "wait_market"
    # a backed "avoid" stays an avoid: it is not a buy either way
    backed = final_verdict(_doc(avoid="probable", exposure=0.0), _entry("avoid"))
    assert backed is not None and backed.code == "avoid" and backed.market_warning


def test_no_band_means_no_verdict() -> None:
    assert final_verdict(_doc(), _entry(None, "sell_queue")) is None
    assert final_verdict(_doc(), {"queue_state": "none"}) is None
    assert verdict_fields(None) == {}


# --- holder column --------------------------------------------------------------------------


@pytest.mark.parametrize("band", ["candidate", "middle"])
def test_holder_of_a_candidate_or_middle_holds(band: str) -> None:
    v = final_verdict(_doc(), _entry(band))
    assert v is not None and (v.holder_code, v.holder_label, v.holder_key) == (
        "hold",
        "نگه‌دار",
        "hold",
    )


def test_holder_is_not_pushed_out_by_the_state_veto_or_a_queue() -> None:
    veto = final_verdict(_doc(), _entry("candidate"), _turning("hot"), 7)
    assert veto is not None and veto.code == "wait" and veto.holder_code == "hold"
    queue = final_verdict(_doc(), _entry("candidate", "buy_queue"))
    assert queue is not None and queue.holder_code == "hold"


@pytest.mark.parametrize("grade", ["probable", "proven"])
def test_holder_of_a_backed_avoid_is_asked_to_weigh_a_sale(grade: str) -> None:
    v = final_verdict(_doc(avoid=grade), _entry("avoid"))
    assert v is not None and (v.holder_code, v.holder_label) == ("consider_sell", "فروش را بسنجید")
    assert v.holder_key == "sell" and "بفروش" not in v.holder_headline


def test_holder_of_an_unproven_avoid_holds() -> None:
    v = final_verdict(_doc(avoid="unproven"), _entry("avoid"))
    assert v is not None and v.holder_code == "hold" and "فروش لازم نیست" in v.holder_headline


def test_holder_keeps_the_verdict_with_a_market_warning_when_exposure_is_zero() -> None:
    for band, expect in (("candidate", "hold"), ("middle", "hold"), ("avoid", "hold")):
        v = final_verdict(_doc(exposure=0.0), _entry(band))
        assert v is not None and v.holder_code == expect
        assert v.market_warning and "هشدار بازار" in v.holder_headline
    sale = final_verdict(_doc(avoid="proven", exposure=0.0), _entry("avoid"))
    assert sale is not None and sale.holder_code == "consider_sell" and sale.market_warning


def test_no_plain_sell_is_ever_made_here() -> None:
    for band in ("candidate", "middle", "avoid"):
        for grade in ("unproven", "probable", "proven"):
            v = final_verdict(_doc(cand=grade, avoid=grade), _entry(band))
            assert v is not None and v.code != "sell" and v.holder_code != "sell"
            assert "بفروش" not in v.headline + v.holder_headline


def test_unheld_words_use_wait_not_hold() -> None:
    labels = {
        final_verdict(_doc(), _entry(b)).label  # type: ignore[union-attr]
        for b in ("candidate", "middle", "avoid")
    }
    assert "نگه‌دار" not in labels and "نگهداری" not in labels


# --- the numbers the verdict stands on come from the report ---------------------------------


def test_config_grades_and_fractions_match_the_phase_2_report() -> None:
    cfg = get_engine_config().v2.verdict
    r = json.loads(STUDY.read_text(encoding="utf-8"))
    assert cfg.horizon_days == r["verdict_horizon"]
    prof = r["profiles"][str(cfg.horizon_days)]["basket"]
    n_cand = round(cfg.candidate_top_frac * 10)
    n_avoid = round(cfg.avoid_bottom_frac * 10)
    assert prof["candidate"]["deciles"] == list(range(10 - n_cand + 1, 11))
    assert prof["avoid"]["deciles"] == list(range(1, n_avoid + 1))
    assert GRADES[prof["candidate"]["grade"]] == cfg.candidate_grade
    assert GRADES[prof["avoid"]["grade"]] == cfg.avoid_grade
