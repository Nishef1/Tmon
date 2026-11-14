"""The deep models: they run, they never see a future label, and they find a planted edge."""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from tests.test_adapt import _synthetic_panel  # noqa: E402
from tmon.backtest import deep_study as ds  # noqa: E402
from tmon.backtest.walkforward_study import HORIZONS, WARMUP  # noqa: E402

HI = HORIZONS.index(20)


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds, "EPOCHS", 14)
    monkeypatch.setattr(ds, "N_SAMPLES", 4)
    monkeypatch.setattr(ds, "T_STEPS", 8)


@pytest.fixture(scope="module")
def edge_lab() -> ds.Lab:
    return ds.Lab(_synthetic_panel(WARMUP + 330, 60, edge=3.0, seed=5), torch.device("cpu"))


def _t(lab: ds.Lab) -> int:
    return int(lab.p.D - 1 - HORIZONS[HI])  # a date whose 20-day label is not yet known


@pytest.mark.parametrize("kind", ds.KINDS)
def test_every_kind_fits_and_scores_every_stock_finitely(edge_lab: ds.Lab, kind: str) -> None:
    t = _t(edge_lab)
    f = edge_lab.predictor(kind, 1, HI, t)
    assert f is not None
    s = f(t)
    assert s.shape == (edge_lab.p.X[t].shape[0],) and np.isfinite(s).all()


@pytest.mark.parametrize("kind", ["dmlp", "gru", "tcn"])
def test_a_planted_edge_is_found(edge_lab: ds.Lab, kind: str) -> None:
    ics = []
    for t in range(edge_lab.p.D - 60, edge_lab.p.D - 25):
        f = edge_lab.predictor(kind, 1, HI, t)
        assert f is not None
        y = edge_lab.p.Y[t][:, HI]
        m = np.isfinite(y)
        ics.append(np.corrcoef(f(t)[m], y[m])[0, 1])
    assert np.mean(ics) > 0.1


@pytest.mark.parametrize("kind", ds.KINDS)
def test_labels_unknown_at_the_decision_date_change_nothing(kind: str) -> None:
    """Noise in every label the model may not know leaves its score on that date identical."""
    a = ds.Lab(_synthetic_panel(WARMUP + 330, 60, edge=3.0, seed=5), torch.device("cpu"))
    b = ds.Lab(_synthetic_panel(WARMUP + 330, 60, edge=3.0, seed=5), torch.device("cpu"))
    t = _t(a)
    j = t - HORIZONS[HI] - 1
    rng = np.random.default_rng(0)
    for d in range(j + 1, b.p.D):  # the 20-day label of dates after j is unknown at t
        b.p.Y[d][:, HI] = rng.random(b.p.Y[d].shape[0]) - 0.5
    for d in range(t - 1, b.p.D):  # and so is the 1-day label of dates after t - 2 (the lag input)
        b.p.Y[d][:, 0] = rng.random(b.p.Y[d].shape[0]) - 0.5
    b.seq = ds.Seq(b.p, torch.device("cpu"))
    fa, fb = a.predictor(kind, 3, HI, t), b.predictor(kind, 3, HI, t)
    assert fa is not None and fb is not None
    assert np.allclose(fa(t), fb(t), atol=1e-6)


def test_run_t_reports_ic_and_excess_and_skips_missing_models(edge_lab: ds.Lab) -> None:
    p = edge_lab.p
    ics, _exs, scores = ds.run_t(p, lambda t, _h: p.X[t][:, 0], HI, WARMUP)
    assert np.isfinite(ics[WARMUP]) and ics[WARMUP] > 0  # signal 0 is the planted one
    assert scores[WARMUP] is not None
    none_ics, _e, none_scores = ds.run_t(p, lambda _t, _h: None, HI, WARMUP)
    assert np.isnan(none_ics).all() and all(s is None for s in none_scores)
