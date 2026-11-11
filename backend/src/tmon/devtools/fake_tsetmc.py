"""A local STAND-IN for TSETMC, serving SYNTHETIC data in the reference payload formats.

Purpose: exercise the real ingestion code (HTTP client, parsers, pipeline, intraday poller,
probe) end to end over real sockets when the actual site cannot be reached. It proves our code
works against the *documented* formats; it says nothing about the real service or the market.
Symbols are called "نمونه N", prices are a seeded random walk (``tmon.backtest.synthetic``).

    python -m tmon.devtools.fake_tsetmc [--port 8765] [--live]

then point the ingestion at it:

    TMON_TSETMC_OLD_URL=http://127.0.0.1:8765 TMON_TSETMC_CDN_URL=http://127.0.0.1:8765 ...

Modes
* default ("closed"): the market watch shows the finished session; the daily history includes
  today's bar and equals the watch (so the probe's cross-check can be exercised).
* ``--live``: the history ends yesterday and the watch moves on every request (new trades, a
  jiggling last price, a live order book), so change detection and the intraday poller run.
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from tmon.backtest.synthetic import LIMIT, make_market

TEHRAN = ZoneInfo("Asia/Tehran")
CODE0 = 700000


def _today() -> date:
    return datetime.now(TEHRAN).date()


class FakeMarket:
    def __init__(self, n_inst: int = 24, n_days: int = 560, *, live: bool = False, seed: int = 5):
        self.live = live
        self.n_inst = n_inst
        self._rng = np.random.default_rng(seed)
        self._lock = threading.Lock()
        today = _today()
        # enough trading days to end on today or just before it
        start = today - timedelta(days=int(n_days * 7 / 5) + 20)
        prices, clients, _ = make_market(n_days + 20, n_inst, seed=seed, edge=0.03, start=start)
        last_day = today if not live else today - timedelta(days=1)
        prices = prices.filter(prices["date"] <= last_day)
        clients = clients.filter(clients["date"] <= last_day)
        self.prices = prices
        self.clients = clients
        self.codes = [str(CODE0 + i) for i in range(1, n_inst + 1)]
        self._cum_volume: dict[str, float] = {c: 0.0 for c in self.codes}
        self._last: dict[str, float] = {}
        for i, code in enumerate(self.codes, start=1):
            rows = prices.filter(prices["instrument_id"] == i).sort("date")
            self._last[code] = float(rows["close"][-1])

    def _sym(self, code: str) -> str:
        return f"نمونه{int(code) - CODE0}"

    def _rows(self, code: str) -> pl.DataFrame:
        i = int(code) - CODE0
        return self.prices.filter(self.prices["instrument_id"] == i).sort("date")

    # ---- endpoints ------------------------------------------------------- #

    def market_watch(self) -> str:
        today = _today()
        out = []
        with self._lock:
            for code in self.codes:
                rows = self._rows(code)
                if self.live:
                    yday = float(rows["close"][-1])
                    n_new = int(self._rng.integers(0, 4)) if self._rng.random() < 0.7 else 0
                    if n_new:
                        step = 1 + float(self._rng.normal(0, 0.002))
                        self._last[code] = float(
                            np.clip(
                                round(self._last[code] * step),
                                round(yday * (1 - LIMIT)),
                                round(yday * (1 + LIMIT)),
                            )
                        )
                        self._cum_volume[code] += float(self._rng.integers(1, 40)) * 1000 * n_new
                    final = self._last[code]
                    vol = self._cum_volume[code]
                    hi = max(final, yday)
                    lo = min(final, yday)
                    first = yday
                    value = vol * final
                    trades = int(vol / 4000)
                else:
                    row = rows.filter(rows["date"] == today)
                    if row.height == 0:  # not a trading day: show the last session
                        row = rows.tail(1)
                    r = row.row(0, named=True)
                    yday, final, first = r["prev_close"], r["close"], r["open"]
                    hi, lo, vol, value = r["high"], r["low"], r["volume"], r["value"]
                    trades = int(vol / 4000)
                out.append(
                    ",".join(
                        [
                            code,
                            f"IRO1{code}0001",
                            self._sym(code),
                            f"شرکت نمونه {int(code) - CODE0}",
                            datetime.now(TEHRAN).strftime("%H:%M:%S"),
                            f"{first:.0f}",
                            f"{final:.0f}",
                            f"{final:.0f}",
                            str(trades),
                            f"{vol:.0f}",
                            f"{value:.0f}",
                            f"{lo:.0f}",
                            f"{hi:.0f}",
                            f"{yday:.0f}",
                        ]
                    )
                )
        return "fake@synthetic@" + ";".join(out)

    def history(self, code: str) -> str:
        r = self._rows(code)
        lines = [
            "<TICKER>,<DTYYYYMMDD>,<FIRST>,<HIGH>,<LOW>,<CLOSE>,<VALUE>,<VOL>,<OPENINT>,<PER>,"
            "<OPEN>,<LAST>"
        ]
        sym = self._sym(code)
        for x in r.iter_rows(named=True):
            lines.append(
                f"{sym},{x['date']:%Y%m%d},{x['open']:.0f},{x['high']:.0f},{x['low']:.0f},"
                f"{x['close']:.0f},{x['value']:.0f},{x['volume']:.0f},"
                f"{int(x['volume'] / 4000)},D,{x['prev_close']:.0f},{x['last']:.0f}"
            )
        return "\n".join(lines)

    def client_types(self, code: str) -> str:
        i = int(code) - CODE0
        c = self.clients.filter(self.clients["instrument_id"] == i).sort("date")
        rows = []
        for x in c.iter_rows(named=True):
            rows.append(
                ",".join(
                    [f"{x['date']:%Y%m%d}"]
                    + [
                        f"{x[k]:.0f}"
                        for k in (
                            "buy_count_i",
                            "buy_count_n",
                            "sell_count_i",
                            "sell_count_n",
                            "buy_volume_i",
                            "buy_volume_n",
                            "sell_volume_i",
                            "sell_volume_n",
                            "buy_value_i",
                            "buy_value_n",
                            "sell_value_i",
                            "sell_value_n",
                        )
                    ]
                )
            )
        return ";".join(rows)

    def instrument_info(self, code: str) -> dict[str, Any]:
        i = int(code) - CODE0
        return {
            "instrumentInfo": {
                "insCode": code,
                "lVal18AFC": self._sym(code),
                "lVal30": f"شرکت نمونه {i}",
                "cIsin": f"IRO1{code}0001",
                "sector": {"cSecVal": f"s{i % 5}", "lSecVal": f"بخش نمونه {i % 5}"},
                "cgrValCot": "N1",
                "cgrValCotTitle": "بازار اول (بورس)",
                "flow": 1,
                "flowTitle": "بازار اول",
                "zTitad": 1_000_000_000,
                "baseVol": 5_000_000,
            }
        }

    def best_limits(self, code: str) -> dict[str, Any]:
        with self._lock:
            px = self._last[code]
        tick = max(1, round(px * 0.001))
        rng = self._rng
        return {
            "bestLimits": [
                {
                    "number": n,
                    "pMeDem": px - (n - 1) * tick,
                    "qTitMeDem": int(rng.integers(1, 50)) * 1000,
                    "zOrdMeDem": int(rng.integers(1, 20)),
                    "pMeOf": px + n * tick,
                    "qTitMeOf": int(rng.integers(1, 50)) * 1000,
                    "zOrdMeOf": int(rng.integers(1, 20)),
                }
                for n in range(1, 6)
            ]
        }


def make_handler(market: FakeMarket) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:  # keep the console quiet
            return

        def _send(
            self, body: str, ctype: str = "text/plain; charset=utf-8", status: int = 200
        ) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            p = u.path
            code = q.get("i", [""])[0]
            parts = [x for x in p.split("/") if x]
            body: str | None = None
            ctype = "text/plain; charset=utf-8"
            if p.endswith("MarketWatchInit.aspx"):
                body = market.market_watch()
            elif p.endswith("Export-txt.aspx") and code in market.codes:
                body = market.history(code)
            elif p.endswith("clienttype.aspx") and code in market.codes:
                body = market.client_types(code)
            elif (
                len(parts) == 4
                and parts[:3] == ["api", "Instrument", "GetInstrumentInfo"]
                and parts[3] in market.codes
            ):
                body, ctype = json.dumps(market.instrument_info(parts[3])), "application/json"
            elif (
                parts[:2] == ["api", "BestLimits"] and len(parts) >= 3 and parts[2] in market.codes
            ):
                body, ctype = json.dumps(market.best_limits(parts[2])), "application/json"
            if body is None:
                self._send("not found", status=404)
            else:
                self._send(body, ctype)

    return Handler


def serve(
    port: int = 0, *, live: bool = False, n_inst: int = 24, n_days: int = 560
) -> ThreadingHTTPServer:
    """Start the stand-in on 127.0.0.1 in a daemon thread; ``port=0`` picks a free port."""
    market = FakeMarket(n_inst, n_days, live=live)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(market))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--instruments", type=int, default=24)
    args = ap.parse_args()
    server = serve(args.port, live=args.live, n_inst=args.instruments)
    print(f"synthetic TSETMC stand-in on http://127.0.0.1:{server.server_port} (live={args.live})")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
