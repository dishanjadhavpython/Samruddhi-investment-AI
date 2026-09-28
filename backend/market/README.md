# Market pipeline

Index-level market context for the Market page: the Nifty 50 valuation
temperature, turbulence (drawdown, 200-day average, India VIX) and history
tables. Nothing here reads user data or names a security.

| File | What it does |
|---|---|
| `indicators.py`, `zones.py`, `breaks.py`, `history.py` | Pure, tested maths |
| `signals.py` | Builds the daily `market_signals` row and the chart payloads |
| `market_eod.py`, `lambda_handler.py` | The 19:00 IST job (`terraform/10_market`) |
| `ingest.py` | Loads the valuation files you download by hand |
| `backfill.py` | One-off: full Yahoo history, holidays, breaks, first signals |
| `backtest.py` | Research report: windows, sub-periods, bootstrap intervals |
| `test_market.py` | `uv run test_market.py` |

## Loading the valuation history (manual, once, then occasionally)

The valuation dial and the "What followed from each zone" table need Nifty 50
P/E, P/B, dividend yield and Total Return Index history. NSE Indices' terms
forbid automated collection, so download it yourself:

1. Open https://www.niftyindices.com/reports/historical-data
2. Choose the **NIFTY 50** index.
3. Download **"P/E, P/B & Div.Yield values"** from 1 Jan 1999 to today as CSV.
   If the site limits the date range, download it in pieces; overlapping
   files are fine.
4. Download **"Total Returns Index Values"** for the same dates as CSV.
5. Put every file in `backend/market/nse_data/` (git-ignored; never commit or
   republish NSE data).
6. Check the files, then load them:

   ```bash
   cd backend/market
   uv run ingest.py nse_data/ --dry-run   # parse and report only
   uv run ingest.py nse_data/             # load and recompute the signals
   uv run backtest.py                     # optional: writes reports/backtest-v1-expanding.md
   ```

To add newer days later, download just the recent range and either run
`uv run ingest.py` again or copy the file to the bucket, where the next 19:00
run picks it up:

```bash
aws s3 cp nifty50_pe_pb.csv s3://samruddhi-market-<account-id>/incoming/
```

Files that can't be read move to `rejected/` with the reason in the Lambda log.

## Methodology breaks

NSE has changed how it calculates these ratios without restating history.
`series.py` registers the two known changes (P/E on 31 Mar 2021, P/B on 29 Sep
2023) and older values are scaled onto today's basis. Any new valuation jump
of more than 6% on a day the index moved less than 1% is logged as a
candidate break for a person to review; it is never applied automatically.

## Data licensing

Yahoo Finance and NSE Indices data are for the private demo deployment only. A
public or paid launch needs licensed sources (plan section 10.4).
