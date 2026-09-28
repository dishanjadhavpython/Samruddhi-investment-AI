# Samruddhi AI

Samruddhi AI is a multi-agent portfolio analytics platform for Indian investors, running serverless on AWS. It turns a user's own holdings into readable reports, charts and retirement projections, and shows where the market stands against its own history, through a team of AI agents whose every sentence is checked before anyone sees it.

It is an information and analytics service. It does not give investment advice, buy/sell/hold calls, price targets or model portfolios.

## What It Does

- **Portfolio reports and charts.** Users sign in with Clerk, record accounts, holdings and transactions (by hand or from a CSV such as a Zerodha tradebook), and get AI-written analyses of their own portfolio: allocation, concentration, drift from their own targets, and questions worth taking to a SEBI-registered adviser.
- **Retirement projections.** Monte Carlo projections from the user's age, contributions and target income, shown as ranges.
- **Market context.** A Market page with the Nifty 50's valuation temperature and turbulence (drawdown, 200-day average, India VIX), what followed historically from each valuation zone, and one shared daily market note.
- **Delayed prices.** NSE prices at least 15 minutes delayed during the session, daily bars with candlestick charts, and AMFI NAVs. Every price shows its as-of time, source and delay.
- **Lump sum or stagger explorer.** How investing at once compared with 3, 6 or 12-month plans historically, at index level, with no fund names and no default pick.
- **Performance.** Value history, XIRR, and a Nifty 50 comparison on the same cash flows.

## Architecture

- **Agents**: Planner (orchestrator), Tagger (instrument classification), Reporter (portfolio report), Charter (charts), Retirement (projections), Compliance Checker (reviews every AI-written text) and Signals (daily market note), built with the OpenAI Agents SDK and coordinated over SQS.
- **Research agent**: a Lambda container with Playwright MCP that gathers dated, sourced research twice each weekday for the knowledge base.
- **LLM**: Amazon Nova Pro on AWS Bedrock, through LiteLLM.
- **Knowledge base**: S3 Vectors with a SageMaker Serverless embedding endpoint (all-MiniLM-L6-v2); notes older than 14 days are not used.
- **Data**: Aurora Serverless v2 (PostgreSQL, Data API) for users, portfolios, transactions, jobs and market signals; DynamoDB for delayed intraday prices, so pages can poll without touching Aurora.
- **Schedules**: EventBridge Scheduler in IST for prices (every 5 minutes in session), end-of-day bars and NAVs, the daily market job and research runs.
- **Frontend**: NextJS (Pages Router, static export) on S3 and CloudFront, backed by a FastAPI Lambda API.
- **Trust and safety**: a guardrail that checks every figure against computed facts and blocks advice language, a Compliance Checker agent and a report judge that both fail closed, LangFuse traces and scores, eval suites with published pass rates, and an append-only audit log on S3 Object Lock from which any report can be replayed.

## Repository Layout

| Path | What's there |
|---|---|
| `backend/` | Agents, the API, the pricer, the market job, ingest and the shared `database` library (one uv project each) |
| `frontend/` | The NextJS app |
| `terraform/` | Independent Terraform directories, `2_sagemaker` to `11_audit`, each with its own state |
| `guides/` | Step-by-step deployment guides, parts 1-8 |
| `plans/` | The market intelligence plan and its backtest reference |
| `scripts/` | Frontend deployment and local development |

## Deploying

1. Follow the guides in `guides/` in order, starting with `1_permissions.md`.
2. In each Terraform directory, copy `terraform.tfvars.example` to `terraform.tfvars` and fill it in. Every resource name starts with `name_prefix` (default `samruddhi`).
3. Package Lambdas with `uv run package_docker.py` in each backend directory (Docker Desktop must be running).
4. Review every change with `terraform plan -out=<file>` before `terraform apply <file>`.

All Python runs through [uv](https://docs.astral.sh/uv/): `uv run <script>.py`, never `pip` or bare `python`.

## Data and Compliance

Yahoo Finance prices, AMFI NAV files and manually downloaded NSE Indices history are used for a private demo only. A public or paid launch needs licensed market data, and the regulatory positioning in `plans/realtime-market-intelligence.md` (section 10) should be confirmed with a securities lawyer.

## Tech Stack

Python (uv), OpenAI Agents SDK, LiteLLM, AWS Bedrock (Nova Pro), AWS Lambda, Aurora Serverless v2, DynamoDB, S3 Vectors, SageMaker, SQS, EventBridge Scheduler, API Gateway, CloudFront, S3 Object Lock, NextJS, Clerk, Terraform and LangFuse.

## License

MIT. See [LICENSE](LICENSE).
