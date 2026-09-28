# Samruddhi AI - Project Guide

## Project Overview

**Samruddhi AI** is a multi-agent SaaS for Indian investors. It describes a user's own equity and mutual-fund portfolio, projects retirement scenarios, and puts the market in context: where the Nifty 50 stands against its own history. It is an information and analytics service, not an investment adviser: it never tells anyone what to buy, sell or hold, or when (see "Compliance rules" below).

What is deployed:
- **Multi-agent analysis**: a Planner orchestrates Tagger, Reporter, Charter and Retirement agents; a Compliance Checker reviews every AI-written text; a Signals agent writes one shared daily market note
- **Market data**: delayed NSE prices (15 minutes during the session), daily bars, AMFI NAVs, Nifty 50 valuation and turbulence indicators, a lump sum vs stagger explorer
- **Performance**: a transaction ledger with XIRR and a Nifty 50 comparison on the same cash flows
- **Serverless architecture**: Lambda, Aurora Serverless v2 (Data API), DynamoDB, API Gateway, SQS, EventBridge Scheduler, S3 Vectors, SageMaker Serverless embeddings
- **Production practices**: guardrails, a compliance checker and a judge that fail closed, LangFuse traces and scores, an append-only audit log on S3 Object Lock, eval suites
- **Frontend**: NextJS (Pages Router, static export) on S3 and CloudFront, with Clerk authentication

The roadmap and its status are in `plans/realtime-market-intelligence.md`.

---

## Directory Structure

```
Samruddhi-investment-AI/
├── guides/              # Step-by-step deployment guides, parts 1-8
├── plans/               # Market intelligence plan (phases 0-5) and backtest reference
├── backend/
│   ├── planner/         # Orchestrator agent
│   ├── tagger/          # Instrument classification agent
│   ├── reporter/        # Portfolio report agent (with a judge that fails closed)
│   ├── charter/         # Chart agent
│   ├── retirement/      # Retirement projection agent
│   ├── compliance/      # Compliance Checker agent (structured output)
│   ├── signals/         # Daily shared market note agent
│   ├── researcher/      # Research agent (Lambda container, Playwright MCP)
│   ├── scheduler/       # Starts research runs on a schedule
│   ├── ingest/          # Knowledge-base ingest Lambda (S3 Vectors)
│   ├── pricer/          # Prices, daily bars, NAVs, snapshots, delayed intraday prices
│   ├── market/          # Daily market job: series, indicators, zones, backtest
│   ├── database/        # Shared library: models, guardrails, audit, returns, market_live
│   ├── evals/           # Eval suites, replay from the audit log, end-to-end check
│   └── api/             # FastAPI backend for the frontend
├── frontend/            # NextJS React application
├── terraform/           # Infrastructure as Code, independent directories
│   ├── 2_sagemaker/     # Embedding endpoint
│   ├── 3_ingestion/     # S3 Vectors, ingest Lambda, API Gateway
│   ├── 4_researcher/    # Researcher Lambda and its schedule
│   ├── 5_database/      # Aurora Serverless v2
│   ├── 6_agents/        # Agent Lambdas and SQS
│   ├── 7_frontend/      # CloudFront, S3, API Lambda and API Gateway
│   ├── 8_enterprise/    # CloudWatch dashboards and alarms
│   ├── 9_pricer/        # Pricer Lambda and its IST schedules
│   ├── 10_market/       # Daily market job and the DynamoDB price tables
│   └── 11_audit/        # Audit log bucket (S3 Object Lock)
└── scripts/             # Frontend deployment and local development
```

---

## Deployment Guides

Read the guides in `guides/` in order (1-8) for the full background before changing infrastructure:

1. **AWS permissions** (1_permissions.md): IAM group and policies, AWS CLI
2. **SageMaker** (2_sagemaker.md): serverless embedding endpoint (all-MiniLM-L6-v2)
3. **Ingestion** (3_ingest.md): S3 Vectors bucket and index, ingest Lambda, API key
4. **Researcher** (4_researcher.md): research agent with Bedrock Nova Pro and Playwright MCP, optional schedule
5. **Database** (5_database.md): Aurora Serverless v2 with the Data API, schema, seed data, shared library
6. **Agents** (6_agents.md): agent Lambdas and SQS orchestration
7. **Frontend** (7_frontend.md): Clerk, NextJS, API Lambda, CloudFront
8. **Enterprise** (8_enterprise.md): scaling, security, dashboards, guardrails, LangFuse

Parts 9-11 (pricer, market job, audit log) follow the same pattern; `plans/realtime-market-intelligence.md` and each directory's outputs describe them.

---

## Working Rules

### Python: always uv

There are uv projects in every directory that needs one. A uv project inside another is fine, although uv may show a warning.

Always use `uv add package` and `uv run module.py`. NEVER use `pip install xxx`, and NEVER `python -c "code"`, `python -m module` or `python script.py`. It is VERY IMPORTANT not to use the python command outside a uv project.

Prefer Python scripts run with uv over shell or PowerShell scripts, which are platform dependent. The project must work on Windows, Mac (Intel or Apple Silicon) and Linux.

### Diagnose before fixing ⚠️ MOST IMPORTANT

**Don't jump to conclusions and write lots of code before the problem is understood.**

Avoid:
- defensive code with `isinstance()` checks before understanding the root cause
- try/except blocks that hide the real error
- workarounds that mask the actual problem
- several changes at once, which make debugging impossible

Instead:
1. **Reproduce the issue**: get exact error messages, logs and commands
2. **Identify the root cause**: CloudWatch logs, the AWS Console, error traces
3. **Explain what you think is happening** and confirm it
4. **Propose a minimal fix**: one change at a time
5. **Test and verify** before moving on

Establish context first: which parts are deployed, what the goal is, and the actual error rather than an interpretation of it.

### Terraform

- Each directory is **independent**, with its own local state and `terraform.tfvars` (copy `terraform.tfvars.example`). State files and tfvars are git-ignored.
- Every resource name starts with `name_prefix` (default `samruddhi`). A deployment created with another prefix keeps it by setting `name_prefix` in each `terraform.tfvars` and `NAME_PREFIX` in `.env`; changing it on a live deployment would recreate everything.
- Run `terraform plan -out=<file>`, review the diff, then `terraform apply <file>`. Don't use blind `-auto-approve` applies on the live deployment.
- Use `terraform output` to find ARNs and names from earlier parts.

### Model strategy

Use Amazon Nova Pro (`us.amazon.nova-pro-v1:0` or `eu.amazon.nova-pro-v1:0`) through Bedrock inference profiles, not Claude Sonnet, whose rate limits are too strict for this project. Model access is granted per region in the Bedrock console, and inference profiles may need access in several regions. Nova Pro rate-limits at around 7 concurrent agent runs, so keep eval concurrency at 3.

### Testing

Each agent directory has:
- `test_simple.py`: local run with mocks (`MOCK_LAMBDAS=true`)
- `test_full.py`: invokes the deployed Lambda

Test locally first, then package and deploy, then run `test_full.py`. Pure logic lives in `backend/database/src` with `test_*.py` files next to it (`uv run test_guardrails.py` and so on); the evals run with `cd backend/evals && uv run run_evals.py`.

---

## Compliance Rules

Samruddhi AI runs in information-only mode (plan section 10.1, path A). Every change must keep to it:

1. **Describe, don't prescribe.** No buy, sell, hold, "good time", targets or forecasts, and nothing that tells a user what to do with their money.
2. **Market context is index-level only.** Never attach a zone, colour or verdict to a named security.
3. **Maths in code, words from the LLM.** Figures are computed deterministically; agents only explain them, and `src/guardrails.py` checks every figure against the computed facts.
4. **Every AI-written text** goes through the guardrail and the Compliance Checker before anyone sees it; failures are withheld, never shown unchecked.
5. **Every price shows its as-of time, source and delay.** Yahoo Finance and niftyindices.com data are for a private demo only; a public launch needs licensed data (plan section 10.4).
6. **Never scrape or republish NSE Indices data.** Valuation history is downloaded by hand.

---

## Agent Strategy: OpenAI Agents SDK

Each agent directory has the same structure:
1. `lambda_handler.py`: the Lambda function that runs the agent
2. `agent.py`: agent creation and tools
3. `templates.py`: prompts

Use the latest idiomatic OpenAI Agents SDK APIs. The package is `openai-agents`, not `agents`: `uv add openai-agents`, then `from agents import Agent, Runner, trace`.

Bedrock is reached through LiteLLM:

```python
model = LitellmModel(model=f"bedrock/{model_id}")
```

LiteLLM needs this environment variable (other services use `AWS_REGION` or `DEFAULT_AWS_REGION`, but LiteLLM reads `AWS_REGION_NAME`; see https://docs.litellm.ai/docs/providers/bedrock):

```python
os.environ["AWS_REGION_NAME"] = bedrock_region
```

Because of a LiteLLM and Bedrock limitation, an agent uses **either** structured outputs **or** tools, never both.

The standard pattern in `lambda_handler.py`:

```python
    model, tools, task = create_agent(job_id, portfolio_data, user_preferences, db)

    with trace("Retirement Agent"):
        agent = Agent(
            name="Retirement Specialist",
            instructions=RETIREMENT_INSTRUCTIONS,
            model=model,
            tools=tools
        )

        result = await Runner.run(
            agent,
            input=task,
            max_turns=20
        )

        response = result.final_output
```

When a tool needs to know the user or job, pass context the idiomatic way:

```python
with trace("Reporter Agent"):
        agent = Agent[ReporterContext](
            name="Report Writer", instructions=REPORTER_INSTRUCTIONS, model=model, tools=tools
        )

        result = await Runner.run(
            agent,
            input=task,
            context=context,
            max_turns=10,
        )

        response = result.final_output
```

```python
@function_tool
async def get_market_insights(
    wrapper: RunContextWrapper[ReporterContext], symbols: List[str]
) -> str:
...
```

---

## Common Issues

Most issues come from regions: check environment variables and terraform settings (everything should flow from tfvars).

### 1. `package_docker.py` fails

- **Usual cause**: Docker Desktop isn't running (`docker ps` fails). Start it and wait for it to finish starting.
- A "Mounts denied" error means Docker can't see the temp directory: add it under Docker Desktop → Settings → Resources → File Sharing.
- The uv warning about nested projects is a red herring.
- Agent Lambdas sit close to the 250 MB unzipped limit; new agents start from `backend/compliance/uv.lock`.

### 2. Bedrock access denied or model not found

- Which model, which region, and has access been granted in the Bedrock console?
- Inference profiles may need access in several regions.
- LiteLLM needs `AWS_REGION_NAME`. Check nothing is hard-coded and tfvars are right; log the region in use.

### 3. `terraform apply` fails

- Does `terraform.tfvars` exist, with every value from `terraform.tfvars.example`?
- Are values from earlier parts set? `cd terraform/X && terraform output`.
- Is `name_prefix` the same in every directory?

### 4. Lambda failures

- Logs: `aws logs tail /aws/lambda/<name_prefix>-<agent> --follow`
- Environment variables in the Lambda console or tfvars
- IAM role permissions
- Was the package built with Docker for linux/amd64?

### 5. Aurora connection fails

- `aws rds describe-db-clusters`: is it "available", with `EnableHttpEndpoint: true`?
- Do the ARNs in the environment match `terraform output` in `5_database`?
- A new cluster takes 10-15 minutes to initialise.
- Migrations: `cd backend/database && uv run run_migrations.py` (tracked in `schema_migrations`).

---

## Architecture Quick Reference

```
Browser → CloudFront → S3 (static NextJS)
        → API Gateway → API Lambda (FastAPI, Clerk JWT)
              ├─ Aurora (Data API): users, accounts, positions, transactions, jobs, market signals
              ├─ DynamoDB: delayed prices for /api/market/snapshot (never Aurora)
              └─ SQS → Planner ──┬─ market context (Aurora)
                                 ├─ Tagger
                                 ├─ Reporter ─┐
                                 ├─ Charter ──┼─ Compliance Checker → Aurora → Browser
                                 └─ Retirement┘
EventBridge Scheduler (IST)
  ├─ every 5 min in session → Pricer → Aurora + DynamoDB
  ├─ 16:15 and 23:30 → Pricer (final bars, NAVs, portfolio snapshots)
  ├─ 19:00 → market job → market signals, charts, digest → Signals agent (daily note)
  └─ 08:00 and 18:00 → Researcher → ingest → S3 Vectors
Every agent run → audit log (S3 Object Lock) and LangFuse
```

---

## Cost Management

- Aurora is the largest cost: destroy it when not working on the project.
- Destroy in reverse order with `terraform destroy` in each directory (11 → 2). Turn off `10_market` and `9_pricer` schedules before destroying Aurora.
- `11_audit` uses Object Lock: records can't be deleted until their retention ends.
- Watch costs in AWS Cost Explorer and keep budget alerts on.

---

## Key Files

- `.env`: root environment variables, including `NAME_PREFIX`
- `frontend/.env.local`: Clerk configuration
- `terraform/*/terraform.tfvars`: per-directory configuration (copy from `.example`)
- `backend/*/templates.py`: prompts
- `backend/database/src/guardrails.py`: never-use phrasing and figure checks
- `plans/realtime-market-intelligence.md`: roadmap, decisions and data licensing
