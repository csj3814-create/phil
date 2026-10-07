"""Shared plumbing for the non-Polymarket venue adapters. Stdlib only.

PROTECTED CORE — the trading agent must not edit files under core/.

The rest of core/ was written against Polymarket's gamma market records and
CLOB order books. Rather than rewrite every consumer, each venue adapter
(venue_manifold.py, venue_kalshi.py) translates its own API into that same
shape, and core/pmapi.py dispatches to the adapter named by
config/protected.json "venue". This module holds what both adapters share:
HTTP with retries and the gamma-shaped record builder.

Token ids are synthetic: "<market_id>::<outcome>", so a ledger row's
token_id always names its own market and outcome.
"""
import datetime as dt
import json
import subprocess
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "pearl-explorations-paper-trader/0.1"}
TOKEN_SEP = "::"


def get_json(url, params=None, retries=3):
    """GET url as JSON: urllib with retries, then one curl attempt (some
    hosts reset Python's TLS handshake intermittently)."""
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
            if getattr(e, "code", None) == 404:
                break
            time.sleep(1.5 * (attempt + 1))
    try:
        out = subprocess.run(["curl", "-sf", "--max-time", "30", "-H",
                              f"User-Agent: {UA['User-Agent']}", url],
                             capture_output=True, text=True, timeout=40, check=True)
        return json.loads(out.stdout)
    except Exception as e_curl:  # noqa: BLE001 — surface both halves
        raise RuntimeError(f"GET {url} failed after {retries} tries: {last_err} "
                           f"(curl: {e_curl})") from e_curl


def token_id(market_id, outcome):
    return f"{market_id}{TOKEN_SEP}{outcome}"


def split_token(tok):
    market_id, _, outcome = str(tok).rpartition(TOKEN_SEP)
    if not market_id:
        raise RuntimeError(f"not a venue token id: {tok!r}")
    return market_id, outcome


def iso_from_ms(ms):
    if ms in (None, ""):
        return None
    try:
        t = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(
            milliseconds=float(ms))
    except (OverflowError, ValueError):
        return "9999-12-31T00:00:00Z"   # "never closes" sentinels overflow
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def gamma_record(*, market_id, question, p_yes, end_date, closed, slug="",
                 description="", volume24hr=0.0, volume=0.0, liquidity=0.0,
                 event_id=None, event_slug=None, created_at=None,
                 closed_time=None, resolved_outcome=None, category=None,
                 url=None, extra=None):
    """A gamma-shaped binary market record.

    resolved_outcome "Yes"/"No" makes outcomePrices decisive (1/0) so
    core/resolve.py settles it; anything else leaves the live price, which
    resolve.py reads as not-yet-decisive (and voids after the grace period).
    """
    outcomes = ["Yes", "No"]
    if resolved_outcome == "Yes":
        prices = [1.0, 0.0]
    elif resolved_outcome == "No":
        prices = [0.0, 1.0]
    else:
        p = min(max(float(p_yes if p_yes is not None else 0.5), 0.0), 1.0)
        prices = [round(p, 4), round(1 - p, 4)]
    rec = {
        "id": str(market_id),
        "question": question,
        "slug": slug or str(market_id),
        "description": description or "",
        "endDate": end_date,
        "closed": bool(closed),
        "closedTime": closed_time,
        "createdAt": created_at,
        "outcomes": json.dumps(outcomes),
        "outcomePrices": json.dumps([str(p) for p in prices]),
        "clobTokenIds": json.dumps([token_id(market_id, o) for o in outcomes]),
        "volume24hr": float(volume24hr or 0),
        "volumeNum": float(volume or 0),
        "liquidityNum": float(liquidity or 0),
        "events": [{"id": event_id or str(market_id),
                    "slug": event_slug or slug or str(market_id)}],
        "category": category,
        "url": url,
    }
    if extra:
        rec.update(extra)
    return rec


def window_filter(recs, params):
    """Apply the gamma query params every adapter emulates client-side:
    end_date_min/max, volume_num_min, liquidity_num_min, then order/ascending.
    Returns a new list; offset/limit slicing is the caller's."""
    lo = parse_iso(params.get("end_date_min"))
    hi = parse_iso(params.get("end_date_max"))
    vmin = float(params.get("volume_num_min") or 0)
    lmin = float(params.get("liquidity_num_min") or 0)
    out = []
    for r in recs:
        end = parse_iso(r.get("endDate"))
        if lo and (end is None or end < lo):
            continue
        if hi and (end is None or end > hi):
            continue
        if r.get("volumeNum", 0) < vmin or r.get("liquidityNum", 0) < lmin:
            continue
        out.append(r)
    order = params.get("order")
    keyfn = {
        "endDate": lambda r: r.get("endDate") or "9999",
        "volume24hr": lambda r: r.get("volume24hr", 0),
        "volume": lambda r: r.get("volumeNum", 0),
        "volumeNum": lambda r: r.get("volumeNum", 0),
        "liquidity": lambda r: r.get("liquidityNum", 0),
        "liquidityNum": lambda r: r.get("liquidityNum", 0),
        "createdAt": lambda r: r.get("createdAt") or "",
    }.get(order)
    if keyfn:
        asc = str(params.get("ascending", "true")).lower() == "true"
        out.sort(key=keyfn, reverse=not asc)
    return out


def page(recs, params):
    offset = int(params.get("offset") or 0)
    limit = int(params.get("limit") or 100)
    return recs[offset:offset + limit]
