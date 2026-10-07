# Venue: Kalshi (branch `kalshi`)

Operator-owned. Read this before CYCLE.md on this branch.

Polymarket blocks the operator's region (HTTP 451), so this branch runs the
same experiment on [Kalshi](https://kalshi.com) prices. Kalshi is a US
CFTC-regulated exchange; its market data API is public. This repo holds no
Kalshi account or key and cannot place a Kalshi order: every bet is paper,
recorded only in `journal/ledger.jsonl`.

## What changes

| CYCLE.md says | On this branch it means |
|---|---|
| gamma market / `market_id` | Kalshi market ticker (e.g. `KXHIGHNY-26OCT08-T75`) |
| event / `event_id` | Kalshi event ticker; its markets are the rungs (strikes, candidates) |
| outcome | `"Yes"` or `"No"` — every Kalshi market is binary |
| question | `"<event title> — <rung>"`; the full rules are in the market `description` |
| CLOB token / `token_id` | `"<ticker>::Yes"` / `"<ticker>::No"` |
| CLOB best ask (fill price) | average price walking the real order book for the protected max stake ($10), PLUS Kalshi's taker fee (0.07·P·(1−P) per contract) |
| `volume24hr`, `volumeNum` | contracts, not dollars |
| `liquidityNum` | open interest (contracts) — Kalshi publishes no liquidity figure |
| `endDate` | expected expiration (when the outcome is known); the trading close can be later |
| tags (`tag_id`) | Kalshi event categories (`strategy/tools/tags.py list`) |

## Mechanics worth knowing

- Settlement is by the exchange against the source named in the rules
  (BLS, NWS station, league result...). Rules are precise — read the rung's
  strike and the source before estimating; "above 75°F" and "75-76°F" are
  different markets.
- Ladders: an event's rungs are mutually exclusive buckets or nested
  thresholds. `python3 strategy/tools/siblings.py <ticker>` lists the event;
  the cross-market edge class applies exactly as on Polymarket.
- Fees make thin edges negative: at P=0.5 the fee is 1.75¢ per contract.
  `quote.py` shows the raw book; `ledger_fill_ask` in its output is the
  all-in fill.
- The first `scan.py` of a cycle crawls every open event (1-2 minutes) and
  caches it in `.cache/` for 20 minutes.
- `core/resolve.py` waits 21 days past the expected expiration before
  voiding: Kalshi markets can stay open up to two weeks after a delay.

## Steps that do not apply here

- Step 5a (mech second opinions) and REAL.md: Polymarket/Pearl Connect only.
  `loop.sh --real` refuses on this branch.
- `core/odds.py` still works (sports benchmarks are venue-independent).
- `core/screen_replay.py` replays Polymarket history only.

## Starting state (2026-10-07)

Fresh ledger and forecasts (the Polymarket record is in
`journal/polymarket-archive/` and on `main`). `strategy/discovery.py` was
reseeded with Kalshi queries; it is yours to tune from scan's stderr.
