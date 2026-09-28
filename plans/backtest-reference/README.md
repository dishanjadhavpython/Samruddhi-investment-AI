# Backtest reference scripts

These are the scripts behind the numbers in `../realtime-market-intelligence.md`, section 5 (the zone tables and the lump sum vs stagger comparison). They were written during research, not as production code. Phase 2 of the plan ports them into `backend/market/` as a proper uv project with tests.

## Data they expect

Put two files in a `nse_data/` folder next to the scripts. The folder is not committed, because NSE Indices' terms of use forbid republishing its data.

| File | Contents | Record shape |
|---|---|---|
| `pepb.json` | Nifty 50 daily P/E, P/B and dividend yield, 1999 onwards | `{"DATE": "30 Dec 1999", "pe": "24.09", "pb": "4.30", "divYield": "1.02"}` |
| `tri.json` | Nifty 50 Total Return Index, mid-1999 onwards | `{"Date": "30 Dec 1999", "TotalReturnsIndex": "1562.92"}` |

Download both by hand from https://www.niftyindices.com/reports/historical-data ("P/E, P/B & Div.Yield values" and "Total returns Index Values"), and convert them to the shapes above. NSE Indices' terms prohibit automated collection without written consent. A commercial deployment needs an NSE Indices data licence.

## What each script does

| Script | Purpose |
|---|---|
| `analyze.py` | Spearman correlations of P/E, P/B and DY with forward 1/3/5/7-year TRI returns, by quintile |
| `analyze2.py` | Trend (200-day average), drawdown and sub-period stability checks |
| `breaks.py`, `breaks2.py` | Finds the methodology breaks (P/E on 31 Mar 2021, P/B on 29 Sep 2023) |
| `adjusted.py` | Chain-links the breaks and builds the walk-forward valuation temperature and its zone table |
| `stp_adj.py` | Lump sum vs 3/6/12-month staggered plans, conditioned on the valuation zone |
| `intrayear.py` | Intra-year dips against calendar-year returns |

Run any of them with `uv run <script>.py`. Each script declares its own dependencies in its header.
