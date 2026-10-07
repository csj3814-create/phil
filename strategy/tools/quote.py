#!/usr/bin/env python3
"""Preview the live CLOB book for an outcome token before placing a bet.

Usage: python3 strategy/tools/quote.py <token_id> [<token_id> ...]

Lesson from 2026-07-30 cycle: core/scan.py outcome_prices are stale mids;
fills happen at the best ask, which can be several cents worse on
near-resolved markets. Check the ask here and apply risk.json min_edge to
the ASK, not the scan price, before calling core/ledger.py place.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "core"))
import pmapi  # noqa: E402

# Venue note (operator, 2026-10-07): book reads go through core/pmapi.py, which
# answers in CLOB shape for whichever venue config/protected.json names. The
# old direct clob.polymarket.com fetch (and its urllib/curl TLS workaround)
# lives in git history. On Manifold the "book" is the AMM quote at the
# protected stake; on Kalshi it is the real order book, asks derived from the
# opposite side's bids, fee NOT included (pmapi.best_prices includes it).


def main(token_ids):
    for tid in token_ids:
        try:
            book = pmapi.clob_book(tid)
            fill_bid, fill_ask = pmapi.best_prices(tid)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"token_id": tid, "error": str(e)[:200]}))
            continue
        asks = sorted((float(a["price"]), float(a["size"])) for a in book.get("asks", []))
        bids = sorted(((float(b["price"]), float(b["size"])) for b in book.get("bids", [])), reverse=True)
        print(json.dumps({
            "token_id": tid,
            "venue": pmapi.VENUE,
            "best_ask": asks[0] if asks else None,
            "best_bid": bids[0] if bids else None,
            "spread": round(asks[0][0] - bids[0][0], 4) if asks and bids else None,
            "top_asks": asks[:3],
            "ledger_fill_ask": fill_ask,
        }))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
