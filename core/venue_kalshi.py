"""Kalshi adapter (read-only public market data). Stdlib only.

PROTECTED CORE — the trading agent must not edit files under core/.

Translates Kalshi's public Trade API v2 (no key needed for market data) into
the gamma/CLOB shapes the rest of core/ consumes; see venue_common.py. This
adapter only READS prices — nothing here can place an order, and there is no
Kalshi account or key anywhere in this repo.

Ids: a gamma "market id" is the Kalshi market ticker
(e.g. KXHIGHNY-26OCT08-T75); the event id is the event ticker. Every Kalshi
market is binary Yes/No; a multi-outcome question is an event of several
markets (strikes, candidates), so the question text is
"<event title> — <market yes_sub_title>".

Units: Kalshi contracts pay $1, prices are dollars per contract. volume24hr /
volumeNum are contract counts and liquidityNum is open interest (contracts) —
Kalshi publishes no gamma-style liquidity figure. Queries written for
Polymarket dollar floors need re-tuning (strategy/discovery.py).

Fill model (the honest-fill rule of core/ledger.py): the ask is the average
price of walking the order book for `max_stake_usd` dollars, PLUS Kalshi's
taker fee (0.07 * P * (1-P) per contract), so a paper fill costs what a real
one would. Kalshi books are bid-only: a Yes ask is 1 - a No bid.

Discovery: Kalshi has no server-side sort or volume filter, so
gamma_markets() crawls every open event once (about 1-2 minutes), keeps a
compact copy in .cache/kalshi-universe.json for CACHE_TTL_S, and filters and
sorts client-side. Single-market reads (gamma_market) are always live.
"""
import datetime as dt
import json
import os
import pathlib
import time

import venue_common as vc

API = "https://api.elections.kalshi.com/trade-api/v2"
VOID_GRACE_HOURS = 24 * 21    # Kalshi markets can close up to two weeks late
FEE_RATE = 0.07
CACHE_TTL_S = 20 * 60
MAX_EVENT_PAGES = 200
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "kalshi-universe.json"
TAG_MAP = {100328: "Economics", "100328": "Economics"}
OPEN_STATUSES = ("active", "open", "initialized")

_PROTECTED = json.loads((ROOT / "config" / "protected.json").read_text(encoding="utf-8"))
QUOTE_STAKE = float(_PROTECTED.get("max_stake_usd", 10.0))

_event_cache = {}
_universe = None
_query_cache = {}


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _price(m, key):
    """Dollar price from the *_dollars field, falling back to legacy cents."""
    if m.get(f"{key}_dollars") not in (None, ""):
        return _f(m[f"{key}_dollars"], None)
    if m.get(key) not in (None, ""):
        return _f(m[key], 0) / 100
    return None


def _p_yes(m):
    bid, ask = _price(m, "yes_bid"), _price(m, "yes_ask")
    if bid and ask and 0 < bid < ask < 1:
        return (bid + ask) / 2
    last = _price(m, "last_price")
    if last and 0 < last < 1:
        return last
    if bid and 0 < bid < 1:
        return bid
    if ask and 0 < ask < 1:
        return ask
    return 0.5


def _question(event, m):
    title = (event or {}).get("title") or m.get("title") or m.get("ticker")
    sub = m.get("yes_sub_title") or ""
    return f"{title} — {sub}" if sub and sub != title else title


def _to_gamma(m, event, description=""):
    status = (m.get("status") or "").lower()
    result = (m.get("result") or "").lower()
    resolved = {"yes": "Yes", "no": "No"}.get(result)
    closed = status not in OPEN_STATUSES
    return vc.gamma_record(
        market_id=m["ticker"],
        question=_question(event, m),
        p_yes=_p_yes(m),
        end_date=m.get("expected_expiration_time") or m.get("close_time"),
        closed=closed,
        slug=m["ticker"].lower(),
        description=description,
        volume24hr=_f(m.get("volume_24h_fp", m.get("volume_24h"))),
        volume=_f(m.get("volume_fp", m.get("volume"))),
        liquidity=_f(m.get("open_interest_fp", m.get("open_interest"))),
        event_id=m.get("event_ticker"),
        event_slug=(m.get("event_ticker") or "").lower(),
        created_at=m.get("open_time") or m.get("created_time"),
        closed_time=m.get("settlement_ts") or (m.get("close_time") if closed else None),
        resolved_outcome=resolved if closed else None,
        category=(event or {}).get("category"),
        url=f"https://kalshi.com/markets/{(event or {}).get('series_ticker', '').lower()}",
        extra={"venue": "kalshi", "kalshi_status": status,
               "series_ticker": (event or {}).get("series_ticker")},
    )


def _event(event_ticker):
    if event_ticker not in _event_cache:
        d = vc.get_json(f"{API}/events/{event_ticker}",
                        {"with_nested_markets": "true"})
        ev = d.get("event") or {}
        ev.setdefault("markets", d.get("markets") or ev.get("markets") or [])
        _event_cache[event_ticker] = ev
    return _event_cache[event_ticker]


# --- universe crawl -------------------------------------------------------------

def _compact(ev, m):
    """The fields gamma emulation needs, without the long rules text."""
    keep = ("ticker", "event_ticker", "yes_sub_title", "title", "status", "result",
            "expected_expiration_time", "close_time", "open_time", "created_time",
            "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars",
            "yes_bid", "yes_ask", "last_price", "volume_fp", "volume_24h_fp",
            "open_interest_fp", "volume", "volume_24h", "open_interest")
    c = {k: m[k] for k in keep if k in m}
    c["_event"] = {"title": ev.get("title"), "category": ev.get("category"),
                   "series_ticker": ev.get("series_ticker")}
    return c


def _crawl():
    out, cursor = [], ""
    for _ in range(MAX_EVENT_PAGES):
        params = {"status": "open", "with_nested_markets": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        d = vc.get_json(f"{API}/events", params)
        for ev in d.get("events") or []:
            for m in ev.get("markets") or []:
                if (m.get("status") or "").lower() in OPEN_STATUSES:
                    out.append(_compact(ev, m))
        cursor = d.get("cursor")
        if not cursor or not d.get("events"):
            break
    return out


def universe():
    global _universe
    if _universe is not None:
        return _universe
    try:
        blob = json.loads(CACHE.read_text())
        if time.time() - blob["ts"] < CACHE_TTL_S:
            _universe = blob["markets"]
            return _universe
    except (OSError, ValueError, KeyError):
        pass
    markets = _crawl()
    CACHE.parent.mkdir(exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"ts": time.time(), "markets": markets}))
    os.replace(tmp, CACHE)
    _universe = markets
    return _universe


# --- gamma emulation --------------------------------------------------------

def gamma_markets(**params):
    key = tuple(sorted((k, str(v)) for k, v in params.items()
                       if k not in ("offset", "limit")))
    if key not in _query_cache:
        if str(params.get("closed", "false")).lower() == "true":
            raise RuntimeError("kalshi adapter: closed-market listing not supported")
        cat = params.get("tag_id")
        cat = TAG_MAP.get(cat, cat)
        recs = []
        for c in universe():
            ev = c.get("_event") or {}
            if cat not in (None, "") and str(ev.get("category") or "").lower() != str(cat).lower():
                continue
            recs.append(_to_gamma(c, ev))
        _query_cache[key] = vc.window_filter(recs, params)
    return vc.page(_query_cache[key], params)


def gamma_market(ticker):
    m = vc.get_json(f"{API}/markets/{ticker}").get("market") or {}
    if not m:
        raise RuntimeError(f"kalshi market {ticker} not found")
    try:
        ev = _event(m.get("event_ticker"))
    except RuntimeError:
        ev = {}
    desc = "\n\n".join(x for x in (m.get("rules_primary"), m.get("rules_secondary")) if x)
    return _to_gamma(m, ev, desc)


def event_markets(event_ticker):
    ev = _event(event_ticker)
    return [_to_gamma(m, ev) for m in ev.get("markets") or []]


# --- order book ------------------------------------------------------------------

def _levels(book, side):
    """[(price_dollars, size)] bids for 'yes' or 'no', either API format."""
    rows = book.get(f"{side}_dollars")
    if rows is not None:
        return [(_f(p), _f(s)) for p, s in rows]
    return [(_f(p) / 100, _f(s)) for p, s in (book.get(side) or [])]


def _book(ticker):
    d = vc.get_json(f"{API}/markets/{ticker}/orderbook")
    book = d.get("orderbook_fp") or d.get("orderbook") or {}
    return _levels(book, "yes"), _levels(book, "no")


def _fill_price(asks, budget):
    """Average all-in price (taker fee included) for spending `budget` dollars
    walking `asks` cheapest first. If the book runs out, the worst level's
    all-in price — the fill is never quoted better than the book supports."""
    spent = shares = 0.0
    worst = None
    for price, size in sorted(asks):
        if not 0 < price < 1 or size <= 0:
            continue
        unit = price + FEE_RATE * price * (1 - price)
        worst = unit
        take = min(size, (budget - spent) / unit)
        spent += take * unit
        shares += take
        if spent >= budget - 1e-9:
            return spent / shares
    return worst


def best_prices(tok):
    ticker, outcome = vc.split_token(tok)
    yes_bids, no_bids = _book(ticker)
    own_bids, other_bids = (yes_bids, no_bids) if outcome == "Yes" else (no_bids, yes_bids)
    asks = [(round(1 - p, 4), s) for p, s in other_bids]
    ask = _fill_price(asks, QUOTE_STAKE)
    good_bids = [p for p, s in own_bids if s > 0 and 0 < p < 1]
    bid = max(good_bids) if good_bids else None
    return (None if bid is None else round(bid, 4),
            None if ask is None else round(min(ask, 1.0), 4))


def clob_book(tok):
    ticker, outcome = vc.split_token(tok)
    yes_bids, no_bids = _book(ticker)
    own, other = (yes_bids, no_bids) if outcome == "Yes" else (no_bids, yes_bids)
    return {"bids": [{"price": str(p), "size": str(s)} for p, s in sorted(own, reverse=True)],
            "asks": [{"price": str(round(1 - p, 4)), "size": str(s)}
                     for p, s in sorted(other, reverse=True)]}


def price_history(tok, hours=24):
    """[{"t": unix_s, "p": price}] from public trades over the last `hours`."""
    ticker, outcome = vc.split_token(tok)
    since = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).timestamp())
    d = vc.get_json(f"{API}/markets/trades",
                    {"ticker": ticker, "min_ts": since, "limit": 1000})
    pts = []
    for t in d.get("trades") or []:
        ts = vc.parse_iso(t.get("created_time"))
        p = _price(t, "yes_price")
        if ts is None or p is None:
            continue
        pts.append({"t": int(ts.timestamp()), "p": round(p if outcome == "Yes" else 1 - p, 4)})
    pts.sort(key=lambda x: x["t"])
    return pts
