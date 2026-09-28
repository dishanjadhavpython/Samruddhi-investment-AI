# Samruddhi AI

Samruddhi AI is an agentic fintech SaaS for portfolio management, AI analysis, and retirement planning. It combines multi-agent orchestration, MCP-based research, AWS managed services, and a production frontend into a single end-to-end system.

---

## Project 1: Financial Planner Agentic System

### What it is
This project focuses on the AI financial planning workflow. A planner agent coordinates specialized agents that analyze a portfolio, generate reports, create charts, and estimate retirement readiness.

### Core architecture
- **Agent orchestration**: OpenAI Agents SDK coordinates the planner, reporter, charter, tagger, and retirement agents.
- **MCP integration**: A Playwright MCP server gives the researcher agent browser access for live financial research.
- **Model layer**: AWS Bedrock provides the language model, using Nova Pro for strong tool use and orchestration.
- **Model bridge**: LiteLLM connects the agents to Bedrock in a consistent way.
- **Embedding layer**: AWS SageMaker serves the embedding model used for retrieval and search.
- **Vector storage**: S3 Vectors stores research and knowledge base content at lower cost than a traditional vector database.
- **Workflow messaging**: SQS routes analysis jobs between the API and background agent workers.
- **Compute**: AWS Lambda handles the backend services and asynchronous jobs, including the researcher service exposed through a public Function URL.

### How it is used for financial planning
This system helps turn raw portfolio data into clear decisions:
- identifies asset allocation and concentration risk
- generates readable portfolio summaries
- creates charts for equity, fixed income, sector, and regional exposure
- estimates retirement readiness with projections and scenario analysis
- retrieves market research to support investment decisions

### Why it matters
Financial planning is complicated because data is scattered across accounts, market context changes quickly, and users need explanations they can trust. This agentic workflow reduces manual analysis time and presents the results in a structured, auditable format.

### Resume-ready version
**Agentic Financial Planner using AWS Bedrock, SageMaker, S3 Vectors, and MCP**
- Built a multi-agent financial planning workflow with planner, reporter, chart, tagger, and retirement agents using the OpenAI Agents SDK.
- Integrated MCP browser automation for live market research and Bedrock-based LLM reasoning.
- Used SageMaker embeddings and S3 Vectors to support semantic retrieval over research content.
- Orchestrated async job processing with SQS, Lambda, and API-driven execution.

---

## Project 2: End-to-End AI Financial SaaS Platform

### What it is
This project is the full Samruddhi AI platform: a production-style SaaS application with authentication, portfolio management, AI analysis, visual reporting, and infrastructure as code.

### Full-stack skills used
- **Frontend**: Next.js Pages Router, React, TypeScript, Tailwind CSS
- **UI system**: shadcn/ui-style design patterns, responsive layouts, accessible forms, loading/empty/error states
- **Authentication**: Clerk sign-in, sign-up, and protected pages
- **Backend**: FastAPI-style API layer and Lambda-based services
- **Data layer**: Aurora Serverless v2 PostgreSQL with Data API
- **Cloud infrastructure**: AWS Lambda, API Gateway, S3, CloudFront, SQS, SageMaker, Bedrock, and S3 Vectors
- **Infrastructure as code**: Terraform for independent, incremental deployments
- **Tooling**: Docker, uv, npm, ESLint, production builds and deployment scripts

### Deployment with Terraform
The infrastructure is split into independent Terraform directories, so each stage can be deployed and destroyed separately:
- `terraform/2_sagemaker`
- `terraform/3_ingestion`
- `terraform/4_researcher`
- `terraform/5_database`
- `terraform/6_agents`
- `terraform/7_frontend`
- `terraform/8_enterprise`

This approach makes the project easier to learn, test, and cost-manage. Each stage has its own `terraform.tfvars`, state file, and outputs.

### How it helps people
This platform helps users understand their investments faster:
- consolidates accounts and holdings in one dashboard
- surfaces analysis instead of raw data
- shows charts and retirement projections in a readable way
- supports more confident financial decisions with clearer context

### Resume-ready version
**Full-Stack AI Financial Planning SaaS on AWS**
- Built a production-style fintech platform with Next.js, Clerk authentication, FastAPI/Lambda services, and responsive analytics dashboards.
- Deployed AWS infrastructure with Terraform across SageMaker, Bedrock, S3 Vectors, Aurora Serverless v2, SQS, Lambda, API Gateway, and CloudFront.
- Designed accessible UI states, reusable components, and a mobile-first interface for portfolio management and AI analysis.
- Implemented asynchronous agent workflows for reports, charts, and retirement projections.

---

## Short resume summary
If you want one concise line for your resume, use this:

**Built Samruddhi AI, an agentic fintech SaaS that combines AWS Bedrock, SageMaker embeddings, MCP-based research, S3 Vectors, Aurora Serverless v2, and a Next.js/Clerk frontend to deliver portfolio analysis, charts, and retirement planning through a multi-agent workflow.**

---

## Suggested resume bullets
- Designed and deployed a multi-agent AI system for financial planning using AWS Bedrock, SageMaker, Lambda, SQS, and MCP browser automation.
- Built a full-stack SaaS frontend with Next.js, TypeScript, Tailwind CSS, and Clerk authentication.
- Orchestrated semantic search and knowledge retrieval with SageMaker embeddings and S3 Vectors.
- Provisioned production AWS infrastructure with Terraform, including Aurora Serverless v2, API Gateway, CloudFront, and Lambda.
- Delivered portfolio summaries, AI-generated reports, chart visualizations, and retirement projections for financial decision support.
