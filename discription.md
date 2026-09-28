# Samruddhi AI

Samruddhi AI is a multi-agent, enterprise-grade SaaS financial planning platform built as a production AI capstone project. It delivers automated equity portfolio analysis, retirement projections, and market research through a team of five specialized AI agents that collaborate via serverless orchestration on AWS.

## What It Does

Samruddhi AI helps users understand their equity portfolios by generating insight-rich reports and charts. Users authenticate through Clerk, upload or connect portfolio data, and receive AI-driven analysis covering instrument classification, portfolio performance, visual charting, retirement outlook, and live market research — all backed by a real, isolated-per-user database.

## Architecture

- **Multi-Agent System**: Planner (orchestrator), Tagger (instrument classification), Reporter (portfolio analysis), Charter (visualizations), and Retirement (projections) agents, built with the OpenAI Agents SDK and coordinated over SQS.
- **Research Agent**: An autonomous App Runner service using AWS Bedrock (Nova Pro model) with Playwright MCP for live web research, optionally scheduled via EventBridge.
- **LLM Backbone**: AWS Bedrock Nova Pro accessed through LiteLLM, chosen over Claude Sonnet for more permissive rate limits at scale.
- **Vector Storage**: S3 Vectors combined with a SageMaker Serverless embedding endpoint (HuggingFace all-MiniLM-L6-v2), offering roughly 90% cost savings over traditional vector databases like OpenSearch.
- **Database**: Aurora Serverless v2 (PostgreSQL) with the Data API enabled, avoiding VPC complexity while keeping each user's data isolated.
- **Frontend**: A NextJS (Pages Router) React application with Clerk authentication, served through S3 and CloudFront, backed by a FastAPI Lambda API.
- **Enterprise Layer**: CloudWatch dashboards and alarms, WAF, VPC endpoints, GuardDuty, guardrails/validation, explainability features, and LangFuse observability.

## Infrastructure Philosophy

The system is deployed entirely through independent Terraform modules (2_sagemaker, 3_ingestion, 4_researcher, 5_database, 6_agents, 7_frontend, 8_enterprise), each with its own local state so learners can build, test, and tear down infrastructure incrementally without complex remote state management.

## Purpose

Originally created as an educational capstone ("Alex — the Agentic Learning Equities Explainer") for a Week 3–4 AI-in-Production course, the project teaches students to design and deploy real multi-agent AI systems on production-grade cloud infrastructure — covering orchestration, cost-optimized retrieval, observability, security, and full-stack delivery — while producing a genuinely usable SaaS product for equity portfolio insight.

## Tech Stack

Python (uv-managed projects), OpenAI Agents SDK, AWS Bedrock, AWS Lambda, Aurora Serverless v2, S3 Vectors, SageMaker, App Runner, SQS, API Gateway, CloudFront, NextJS, Clerk, Terraform, and LangFuse.
