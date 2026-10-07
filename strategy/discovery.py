"""Market discovery — AGENT-EDITABLE.

This is my sensing layer. `core/scan.py` calls `queries()` and then applies the
protected admissibility filters (banned classes, resolution floor, price
bounds) to whatever comes back. I decide WHAT TO LOOK FOR; core decides what is
allowed. A query I write cannot let a banned market through, so I can explore
freely.

VENUE: KALSHI (operator seed, 2026-10-07 — see VENUE.md). The Polymarket
queries and their history live on branch `main`. core/venue_kalshi.py crawls
every open Kalshi event once (cached 20 min) and emulates gamma `/markets`
params client-side:
  order             endDate (expected expiration), volume24hr, volume,
                    liquidity (= open interest), createdAt
  ascending         "true"/"false"
  end_date_min/max  expected-expiration window
  volume_num_min    lifetime volume floor, in CONTRACTS ($1 notional each)
  liquidity_num_min open-interest floor, in contracts
  tag_id            a Kalshi event category: Economics, Financials, Politics,
                    Elections, Sports, Climate and Weather, Entertainment,
                    Companies, Science and Technology, Crypto, Commodities,
                    Mentions, World, Health, AI ... (strategy/tools/tags.py list)
Each Kalshi market is one rung of an event (a strike, a candidate); the
question reads "<event title> — <rung>". Floors below are first guesses —
re-tune them from what scan's stderr reports.

Contract: return a list of dicts of query params. Optional `_label` names the
query in scan's stderr. Anything raising here falls back to core's default
query (loudly), so a bug degrades sensing but never blinds me.
"""


def queries(now, min_end, horizon, args, protected):
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    base = {"closed": "false", "end_date_min": iso(min_end),
            "end_date_max": iso(horizon)}

    return [
        # 1. Where money is moving today inside the window.
        {**base, "_label": "active-24h", "order": "volume24hr",
         "ascending": "false", "volume_num_min": 500},

        # 2. Deep open interest regardless of today's flow.
        {**base, "_label": "deep-oi", "order": "liquidity",
         "ascending": "false", "liquidity_num_min": 2000},

        # 3. Official-number lanes (the fact-finality profile the Polymarket
        #    record favoured — CPI, jobs, Fed, GDP; re-test it here).
        {**base, "_label": "econ", "tag_id": "Economics",
         "order": "volume24hr", "ascending": "false"},
        {**base, "_label": "financials", "tag_id": "Financials",
         "order": "volume24hr", "ascending": "false", "volume_num_min": 200},

        # 4. Weather settles on an official station reading — mechanical.
        {**base, "_label": "weather", "tag_id": "Climate and Weather",
         "order": "volume24hr", "ascending": "false", "volume_num_min": 200},
    ]
