"""Manifold Markets adapter (read-only, play-money venue). Stdlib only.

PROTECTED CORE — the trading agent must not edit files under core/.

Translates Manifold's public API (https://docs.manifold.markets/api) into the
gamma/CLOB shapes the rest of core/ consumes; see venue_common.py.

Scope: BINARY markets on the cpmm-1 AMM only. Manifold settles in mana
(play money); the ledger's "$" figures are mana 1:1 — the experiment measures
calibration (brier_delta), not dollars.

Fill model (the honest-fill rule of core/ledger.py, AMM edition): the ask for
an outcome is the AVERAGE price of buying `max_stake_usd` mana of it from the
pool, from the constant-product invariant Manifold uses
(k = YES^p * NO^(1-p)). Resting limit orders can only improve on that, so the
AMM price is the conservative fill. The bid is the complement of the other
side's ask (selling = buying the opposite side and redeeming a pair).

Resolution: creators resolve Manifold markets, often days after closeTime,
so the void grace in core/resolve.py is two weeks here (VOID_GRACE_HOURS).
YES/NO resolutions settle; MKT (partial) and CANCEL are not decisive and void
after the grace — the ledger has no partial-payout row.
"""
import datetime as dt
import json
import pathlib

import venue_common as vc

API = "https://api.manifold.markets/v0"
VOID_GRACE_HOURS = 24 * 14
RAW_PAGE = 1000          # Manifold's max page size for /search-markets
RAW_CAP = 4000           # most raw markets one gamma_markets() call pages
# Polymarket tag ids that core/ or strategy/ still pass -> Manifold topic slugs
TAG_MAP = {100328: "economics-default", "100328": "economics-default"}
SORT_MAP = {"endDate": "close-date", "volume24hr": "24-hour-vol",
            "liquidity": "liquidity", "liquidityNum": "liquidity",
            "createdAt": "newest", "volume": "most-popular",
            "volumeNum": "most-popular"}

_PROTECTED = json.loads((pathlib.Path(__file__).resolve().parent.parent
                         / "config" / "protected.json").read_text(encoding="utf-8"))
QUOTE_STAKE = float(_PROTECTED.get("max_stake_usd", 10.0))

_market_cache = {}
_query_cache = {}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _usable(m):
    return m.get("outcomeType") == "BINARY" and m.get("mechanism") == "cpmm-1"


def _to_gamma(m):
    close_ms = m.get("closeTime")
    now_ms = _now().timestamp() * 1000
    resolution = m.get("resolution") if m.get("isResolved") else None
    resolved_outcome = {"YES": "Yes", "NO": "No"}.get(resolution)
    p = m.get("probability")
    if resolution == "MKT" and m.get("resolutionProbability") is not None:
        p = m["resolutionProbability"]
    elif resolution == "CANCEL":
        p = 0.5
    closed = bool(m.get("isResolved")) or (close_ms is not None and close_ms < now_ms)
    return vc.gamma_record(
        market_id=m["id"],
        question=m.get("question") or "",
        p_yes=p,
        end_date=vc.iso_from_ms(close_ms),
        closed=closed,
        slug=m.get("slug") or m["id"],
        description=m.get("textDescription") or "",
        volume24hr=m.get("volume24Hours") or 0,
        volume=m.get("volume") or 0,
        liquidity=m.get("totalLiquidity") or 0,
        created_at=vc.iso_from_ms(m.get("createdTime")),
        closed_time=vc.iso_from_ms(m.get("resolutionTime")) if m.get("isResolved") else None,
        resolved_outcome=resolved_outcome,
        url=m.get("url"),
        extra={"venue": "manifold",
               "uniqueBettorCount": m.get("uniqueBettorCount"),
               "resolution": resolution,
               "groupSlugs": m.get("groupSlugs")},
    )


def _raw_market(market_id, fresh=False):
    if fresh or market_id not in _market_cache:
        _market_cache[market_id] = vc.get_json(f"{API}/market/{market_id}")
    return _market_cache[market_id]


# --- gamma emulation --------------------------------------------------------

def gamma_markets(**params):
    key = tuple(sorted((k, str(v)) for k, v in params.items()
                       if k not in ("offset", "limit")))
    if key not in _query_cache:
        _query_cache[key] = vc.window_filter(_search_all(params), params)
    return vc.page(_query_cache[key], params)


def _search_all(params):
    closed = str(params.get("closed", "false")).lower()
    q = {"limit": RAW_PAGE, "contractType": "BINARY",
         "filter": "resolved" if closed == "true" else "open",
         "sort": SORT_MAP.get(params.get("order"), "score")}
    tag = params.get("tag_id")
    if tag not in (None, ""):
        q["topicSlug"] = TAG_MAP.get(tag, str(tag))
    if params.get("term"):
        q["term"] = params["term"]
    hi = vc.parse_iso(params.get("end_date_max"))
    out, offset = [], 0
    while offset < RAW_CAP:
        batch = vc.get_json(f"{API}/search-markets", dict(q, offset=offset))
        if not batch:
            break
        offset += len(batch)
        for m in batch:
            if _usable(m):
                out.append(_to_gamma(m))
        # close-date pages ascend: stop once a page reaches past the window
        if q["sort"] == "close-date" and hi is not None:
            last = vc.parse_iso(vc.iso_from_ms(batch[-1].get("closeTime")))
            if last is not None and last > hi:
                break
        if len(batch) < RAW_PAGE:
            break
    return out


def gamma_market(market_id):
    m = _raw_market(market_id, fresh=True)
    if not _usable(m):
        rec = _to_gamma(m)
        rec["closed"] = True          # unsupported market type: never fillable
        return rec
    return _to_gamma(m)


def event_markets(event_id):
    """Manifold has no multi-market events in this adapter: the market alone."""
    return [gamma_market(event_id)]


# --- AMM fills ---------------------------------------------------------------

def _cpmm_shares(pool, p, outcome, amount):
    """Shares received for buying `amount` mana of `outcome` from a cpmm-1 pool."""
    y, n = float(pool["YES"]), float(pool["NO"])
    if not 0 < p < 1 or y <= 0 or n <= 0:
        raise RuntimeError("degenerate cpmm pool")
    k = y ** p * n ** (1 - p)
    if outcome == "Yes":
        n2 = n + amount
        y2 = (k / n2 ** (1 - p)) ** (1 / p)
        return y + amount - y2
    y2 = y + amount
    n2 = (k / y2 ** p) ** (1 / (1 - p))
    return n + amount - n2


def best_prices(tok):
    """(bid, ask) for an outcome token at the protected stake size."""
    market_id, outcome = vc.split_token(tok)
    m = _raw_market(market_id, fresh=True)
    if not _usable(m) or m.get("isResolved"):
        return (None, None)
    close_ms = m.get("closeTime")
    if close_ms is not None and close_ms < _now().timestamp() * 1000:
        return (None, None)
    other = "No" if outcome == "Yes" else "Yes"
    pool, p = m.get("pool") or {}, float(m.get("p") or 0.5)
    try:
        ask = QUOTE_STAKE / _cpmm_shares(pool, p, outcome, QUOTE_STAKE)
        other_ask = QUOTE_STAKE / _cpmm_shares(pool, p, other, QUOTE_STAKE)
    except (KeyError, RuntimeError, ZeroDivisionError, ValueError):
        return (None, None)
    ask = min(max(ask, 0.0), 1.0)
    bid = min(max(1.0 - other_ask, 0.0), 1.0)
    return (round(bid, 4), round(ask, 4))


def clob_book(tok):
    bid, ask = best_prices(tok)
    return {"bids": [] if bid is None else [{"price": str(bid), "size": "0"}],
            "asks": [] if ask is None else
            [{"price": str(ask), "size": str(round(QUOTE_STAKE / ask, 4))}]}


def price_history(tok, hours=24):
    """[{"t": unix_s, "p": price}] for an outcome over the last `hours`,
    from the probability after each filled bet (oldest first)."""
    market_id, outcome = vc.split_token(tok)
    since = (_now() - dt.timedelta(hours=hours)).timestamp() * 1000
    bets = vc.get_json(f"{API}/bets", {"contractId": market_id, "limit": 1000})
    pts = []
    for b in bets or []:
        if b.get("createdTime", 0) < since or not b.get("amount"):
            continue
        pa = b.get("probAfter")
        if pa is None:
            continue
        p = pa if outcome == "Yes" else 1 - pa
        pts.append({"t": int(b["createdTime"] / 1000), "p": round(p, 4)})
    pts.sort(key=lambda x: x["t"])
    return pts
