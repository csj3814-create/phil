# Venue: Manifold Markets (branch `manifold`)

Operator-owned. Read this before CYCLE.md on this branch.

Polymarket blocks the operator's region (HTTP 451), so this branch runs the
same experiment against [Manifold](https://manifold.markets), a play-money
prediction market with a public API. Nothing here can spend real money:
there is no Manifold account or key in this repo, bets exist only in
`journal/ledger.jsonl`.

## What changes

| CYCLE.md says | On this branch it means |
|---|---|
| gamma market / `market_id` | Manifold market id (e.g. `OI65QnIIys`) |
| outcome | `"Yes"` or `"No"` (BINARY markets only) |
| CLOB token / `token_id` | `"<market_id>::Yes"` / `"<market_id>::No"` |
| CLOB best ask (fill price) | average AMM price of buying the protected max stake (10 mana) of that outcome — slippage included |
| `$` in the ledger and caps | mana, 1:1. Calibration (`brier_delta`) is the result that matters |
| event / siblings | each market is its own event (`siblings.py` returns just it) |
| tags (`tag_id`) | Manifold topic slugs (`strategy/tools/tags.py list`) |
| `endDate` | the market's closeTime (trading stops) |

## Resolution is by the market's creator

- Settles on a YES or NO resolution. Creators often resolve days after
  closeTime, so `core/resolve.py` waits 14 days before voiding.
- `MKT` (partial) and `CANCEL` resolutions never settle a row; they void
  after the grace period.
- Creator quality varies. Read the description's resolution criteria and
  prefer markets whose creator states an objective source; a vague market is
  a skip, not an edge. Record that judgement in the rationale.

## Price and liquidity

- Manifold prices are an AMM plus limit orders. `ledger.py` fills at the AMM
  (conservative; limit orders could only be better). On thin pools a 10-mana
  stake moves the price — `python3 strategy/tools/quote.py <token>` shows
  the fill before you place.
- Many Manifold markets are personal, joke or self-resolving questions. The
  crowd is small: a mispricing can last, but so can a creator's whim.

## Steps that do not apply here

- Step 5a (mech second opinions) and REAL.md: Polymarket/Pearl Connect only.
  `loop.sh --real` refuses on this branch.
- `core/odds.py` still works (sports benchmarks are venue-independent).
- `core/screen_replay.py` replays Polymarket history only.

## Starting state (2026-10-07)

Fresh ledger and forecasts (the Polymarket record is in
`journal/polymarket-archive/` and on `main`). `strategy/discovery.py` was
reseeded with Manifold queries; it is yours to tune from scan's stderr.
