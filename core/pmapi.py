"""Market API facade (read-only). Stdlib only.

PROTECTED CORE — the trading agent must not edit files under core/.

Originally the Polymarket client; now dispatches to the venue named by
config/protected.json "venue" ("polymarket" | "manifold" | "kalshi"). Every
venue answers in Polymarket's gamma/CLOB shapes, so the rest of core/ is
venue-agnostic. Venue adapters: venue_manifold.py, venue_kalshi.py.

Extra helpers beyond the original API, available on every venue:
  price_history(token_id, hours) -> [{"t": unix_s, "p": price}]
  event_markets(event_id)        -> gamma-shaped sibling markets
"""
import json
import pathlib
import time
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "pearl-explorations-paper-trader/0.1"}

VENUE = json.loads((pathlib.Path(__file__).resolve().parent.parent
                    / "config" / "protected.json").read_text(encoding="utf-8")).get("venue", "polymarket")
VOID_GRACE_HOURS = 48


def get_json(url, params=None, retries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as e:  # noqa: BLE001 — retry then surface
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last_err}")


def market_tokens(market):
    """Map outcome name -> token id for a gamma-shaped market record."""
    outcomes = json.loads(market.get("outcomes", "[]"))
    token_ids = json.loads(market.get("clobTokenIds", "[]"))
    return dict(zip(outcomes, token_ids))


if VENUE == "polymarket":
    def gamma_markets(**params):
        return get_json(f"{GAMMA}/markets", params)

    def gamma_market(market_id):
        return get_json(f"{GAMMA}/markets/{market_id}")

    def clob_book(token_id):
        return get_json(f"{CLOB}/book", {"token_id": token_id})

    def best_prices(token_id):
        """Return (best_bid, best_ask) for a CLOB token, None if side empty."""
        book = clob_book(token_id)
        bids = [float(b["price"]) for b in book.get("bids", [])]
        asks = [float(a["price"]) for a in book.get("asks", [])]
        return (max(bids) if bids else None, min(asks) if asks else None)

    def price_history(token_id, hours=24):
        interval = "1h" if hours <= 1 else "6h" if hours <= 6 else "1d" if hours <= 24 else "1w"
        body = get_json(f"{CLOB}/prices-history", {"market": token_id, "interval": interval})
        return body.get("history") if isinstance(body, dict) else body

    def event_markets(event_id):
        return (get_json(f"{GAMMA}/events/{event_id}") or {}).get("markets") or []

elif VENUE in ("manifold", "kalshi"):
    import importlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    _v = importlib.import_module(f"venue_{VENUE}")
    gamma_markets = _v.gamma_markets
    gamma_market = _v.gamma_market
    clob_book = _v.clob_book
    best_prices = _v.best_prices
    price_history = _v.price_history
    event_markets = _v.event_markets
    VOID_GRACE_HOURS = _v.VOID_GRACE_HOURS
    API_BASE = _v.API

else:
    raise RuntimeError(f"config/protected.json venue {VENUE!r} is not supported")
