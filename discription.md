# Samruddhi AI

Samruddhi AI is a multi-agent, enterprise-grade SaaS portfolio analytics platform for Indian investors, running in production on AWS. It delivers automated equity portfolio analysis, retirement projections, market context and market research through a team of seven specialized AI agents that collaborate via serverless orchestration on AWS.

## What It Does

Samruddhi AI helps users understand their equity portfolios by generating insight-rich reports and charts. Users authenticate through Clerk, record their holdings and transactions (by hand or from a broker CSV), and receive AI-driven analysis covering instrument classification, portfolio performance, visual charting, retirement outlook, market context and research, all backed by a real, isolated-per-user database. It describes and explains; it does not give investment advice.

## Architecture

- **Multi-Agent System**: Planner (orchestrator), Tagger (instrument classification), Reporter (portfolio analysis), Charter (visualizations), Retirement (projections), Compliance Checker (reviews every AI-written text) and Signals (daily market note) agents, built with the OpenAI Agents SDK and coordinated over SQS.
- **Research Agent**: An autonomous Lambda container using AWS Bedrock (Nova Pro model) with Playwright MCP for live web research, scheduled twice each weekday via EventBridge.
- **LLM Backbone**: AWS Bedrock Nova Pro accessed through LiteLLM, chosen over Claude Sonnet for more permissive rate limits at scale.
- **Vector Storage**: S3 Vectors combined with a SageMaker Serverless embedding endpoint (HuggingFace all-MiniLM-L6-v2), offering roughly 90% cost savings over traditional vector databases like OpenSearch.
- **Database**: Aurora Serverless v2 (PostgreSQL) with the Data API enabled, avoiding VPC complexity while keeping each user's data isolated. DynamoDB serves delayed intraday prices so pages can poll without touching Aurora.
- **Frontend**: A NextJS (Pages Router) React application with Clerk authentication, served through S3 and CloudFront, backed by a FastAPI Lambda API.
- **Enterprise Layer**: Guardrails and a compliance checker that fail closed, evals with published pass rates, LangFuse observability, an append-only audit log on S3 Object Lock, and CloudWatch dashboards and alarms.

## Infrastructure Philosophy

The system is deployed entirely through independent Terraform modules (2_sagemaker, 3_ingestion, 4_researcher, 5_database, 6_agents, 7_frontend, 8_enterprise, 9_pricer, 10_market, 11_audit), each with its own local state, so infrastructure can be built, tested and torn down incrementally without complex remote state management.

## Purpose

Samruddhi AI shows end to end how a multi-agent AI product runs in production: orchestration, cost-optimized retrieval, observability, compliance guardrails, security and full-stack delivery, while being a genuinely usable SaaS product for equity portfolio insight.

## Tech Stack

Python (uv-managed projects), OpenAI Agents SDK, AWS Bedrock, AWS Lambda, Aurora Serverless v2, DynamoDB, S3 Vectors, SageMaker, SQS, EventBridge Scheduler, API Gateway, CloudFront, NextJS, Clerk, Terraform, and LangFuse.
