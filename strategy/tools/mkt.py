#!/usr/bin/env python3
"""Print a market's question, resolution text and live fill quotes.

Usage: python3 strategy/tools/mkt.py <market_id> [<market_id> ...]

Added 2026-10-07 (first Manifold cycle): VENUE.md says the description's
resolution criteria decide whether a Manifold market is researchable at all,
and the screener batch files carry only the question. This reads the gamma
record (description included) and both outcome quotes through core/pmapi.py.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "core"))
import pmapi  # noqa: E402


def main(ids, desc_chars=1500):
    for mid in ids:
        try:
            m = pmapi.gamma_market(mid)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"market_id": mid, "error": str(e)[:200]}))
            continue
        quotes = {}
        for outcome in ("Yes", "No"):
            try:
                quotes[outcome] = pmapi.best_prices(f"{mid}::{outcome}")
            except Exception as e:  # noqa: BLE001
                quotes[outcome] = str(e)[:100]
        extra = {k: m.get(k) for k in ("uniqueBettorCount", "resolution", "groupSlugs")}
        print(json.dumps({
            "market_id": mid,
            "question": m.get("question"),
            "endDate": m.get("endDate"),
            "closed": m.get("closed"),
            "outcomePrices": m.get("outcomePrices"),
            "liquidity": m.get("liquidity"),
            "volume": m.get("volume"),
            "url": m.get("url"),
            "extra": extra,
            "fill_bid_ask": quotes,
            "description": (m.get("description") or "")[:desc_chars],
        }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
