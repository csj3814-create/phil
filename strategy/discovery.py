"""Market discovery — AGENT-EDITABLE.

This is my sensing layer. `core/scan.py` calls `queries()` and then applies the
protected admissibility filters (banned classes, resolution floor, price
bounds) to whatever comes back. I decide WHAT TO LOOK FOR; core decides what is
allowed. A query I write cannot let a banned market through, so I can explore
freely.

VENUE: MANIFOLD (operator seed, 2026-10-07 — see VENUE.md). The Polymarket
queries and their history live on branch `main`. core/venue_manifold.py
emulates gamma `/markets` params on Manifold's search API:
  closed            "false" -> open markets, "true" -> resolved
  order             endDate (close-date, soonest first), volume24hr,
                    liquidity, createdAt (newest), volume (most popular)
  ascending         client-side re-sort of what was fetched
  end_date_min/max  closeTime window (client-side)
  volume_num_min    lifetime volume floor, in mana
  liquidity_num_min AMM liquidity floor (totalLiquidity), in mana
  tag_id            a Manifold topic slug, e.g. "economics-default",
                    "sports-default", "politics-default", "technology-default"
                    (strategy/tools/tags.py list prints them)
  term              free-text search
Only BINARY cpmm-1 markets are returned. Manifold volumes are play money and
much smaller than Polymarket's: the floors below are first guesses, not
evidence — re-tune them from what scan's stderr reports.

Contract: return a list of dicts of query params. Optional `_label` names the
query in scan's stderr. Anything raising here falls back to core's default
query (loudly), so a bug degrades sensing but never blinds me.
"""


def queries(now, min_end, horizon, args, protected):
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    base = {"closed": "false", "end_date_min": iso(min_end),
            "end_date_max": iso(horizon)}

    return [
        # 1. Everything closing inside the horizon with real trading behind it,
        #    soonest first: fast feedback is what calibration needs.
        {**base, "_label": "closing-soon", "order": "endDate",
         "ascending": "true", "volume_num_min": 2000},

        # 2. Where the crowd is active right now, inside the window.
        {**base, "_label": "active-24h", "order": "volume24hr",
         "ascending": "false"},

        # 3. Deep pools: my fill is closest to the quoted probability here.
        {**base, "_label": "deep-pools", "order": "liquidity",
         "ascending": "false", "liquidity_num_min": 500},

        # 4. Official-number markets (the fact-finality profile the Polymarket
        #    record favoured — re-test it here).
        {**base, "_label": "econ-topic", "tag_id": "economics-default",
         "order": "endDate", "ascending": "true"},
    ]
