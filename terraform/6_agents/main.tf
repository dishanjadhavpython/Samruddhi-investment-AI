terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Using local backend - state will be stored in terraform.tfstate in this directory
  # This is automatically gitignored for security
}

provider "aws" {
  region = var.aws_region
}

# Data source for current caller identity
data "aws_caller_identity" "current" {}

locals {
  sagemaker_endpoint = var.sagemaker_endpoint != "" ? var.sagemaker_endpoint : "${var.name_prefix}-embedding-endpoint"
  # terraform/11_audit creates samruddhi-audit-<account id>; var.audit_bucket overrides it
  audit_bucket = var.audit_bucket != "" ? var.audit_bucket : "${var.name_prefix}-audit-${data.aws_caller_identity.current.account_id}"
}

# ========================================
# SQS Queue for Async Job Processing
# ========================================

resource "aws_sqs_queue" "analysis_jobs" {
  name                       = "${var.name_prefix}-analysis-jobs"
  delay_seconds              = 0
  max_message_size           = 262144
  message_retention_seconds  = 86400 # 1 day
  receive_wait_time_seconds  = 10    # Long polling
  visibility_timeout_seconds = 910   # 15 minutes + 10 seconds buffer (matches Planner Lambda timeout)

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.analysis_jobs_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project = var.name_prefix
    Part    = "6"
  }
}

resource "aws_sqs_queue" "analysis_jobs_dlq" {
  name = "${var.name_prefix}-analysis-jobs-dlq"

  tags = {
    Project = var.name_prefix
    Part    = "6"
  }
}

# ========================================
# IAM Role for Lambda Functions
# ========================================

resource "aws_iam_role" "lambda_agents_role" {
  name = "${var.name_prefix}-lambda-agents-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Project = var.name_prefix
    Part    = "6"
  }
}

# IAM policy for Lambda agents
resource "aws_iam_role_policy" "lambda_agents_policy" {
  name = "${var.name_prefix}-lambda-agents-policy"
  role = aws_iam_role.lambda_agents_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # CloudWatch Logs
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      # SQS access for orchestrator
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.analysis_jobs.arn
      },
      # Lambda invocation for orchestrator to call other agents
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${var.name_prefix}-*"
      },
      # Aurora Data API access
      {
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement",
          "rds-data:BatchExecuteStatement",
          "rds-data:BeginTransaction",
          "rds-data:CommitTransaction",
          "rds-data:RollbackTransaction"
        ]
        Resource = var.aurora_cluster_arn
      },
      # Secrets Manager for database credentials
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = var.aurora_secret_arn
      },
      # S3 Vectors access for all agents
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.vector_bucket}",
          "arn:aws:s3:::${var.vector_bucket}/*"
        ]
      },
      # S3 Vectors API access for all agents
      {
        Effect = "Allow"
        Action = [
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors"
        ]
        Resource = "arn:aws:s3vectors:${var.aws_region}:${data.aws_caller_identity.current.account_id}:bucket/${var.vector_bucket}/index/*"
      },
      # SageMaker endpoint access for reporter agent
      {
        Effect = "Allow"
        Action = [
          "sagemaker:InvokeEndpoint"
        ]
        Resource = "arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:endpoint/${local.sagemaker_endpoint}"
      },
      # Bedrock access for all agents
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        # Replaced ${var.bedrock_region} with * for Bedrock region workaround
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:*:inference-profile/*"
        ]
      },
      # Audit log (terraform/11_audit): write new records only
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "arn:aws:s3:::${local.audit_bucket}/v1/*"
      }
    ]
  })
}

# Attach basic Lambda execution role
resource "aws_iam_role_policy_attachment" "lambda_agents_basic" {
  role       = aws_iam_role.lambda_agents_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ========================================
# S3 Bucket for Lambda Deployments
# ========================================

# S3 bucket for Lambda packages (packages > 50MB must use S3)
resource "aws_s3_bucket" "lambda_packages" {
  bucket = "${var.name_prefix}-lambda-packages-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project = var.name_prefix
    Part    = "6"
  }
}

# Upload Lambda packages to S3
resource "aws_s3_object" "lambda_packages" {
  for_each = toset(["planner", "tagger", "reporter", "charter", "retirement", "compliance", "signals"])

  bucket = aws_s3_bucket.lambda_packages.id
  key    = "${each.key}/${each.key}_lambda.zip"
  source = "${path.module}/../../backend/${each.key}/${each.key}_lambda.zip"
  etag   = fileexists("${path.module}/../../backend/${each.key}/${each.key}_lambda.zip") ? filemd5("${path.module}/../../backend/${each.key}/${each.key}_lambda.zip") : null

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = each.key
  }
}

# ========================================
# Lambda Functions for Each Agent
# ========================================

# Planner (Orchestrator) Lambda
resource "aws_lambda_function" "planner" {
  function_name = "${var.name_prefix}-planner"
  role          = aws_iam_role.lambda_agents_role.arn

  # Using S3 for deployment package (>50MB)
  s3_bucket        = aws_s3_bucket.lambda_packages.id
  s3_key           = aws_s3_object.lambda_packages["planner"].key
  source_code_hash = fileexists("${path.module}/../../backend/planner/planner_lambda.zip") ? filebase64sha256("${path.module}/../../backend/planner/planner_lambda.zip") : null

  handler     = "lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 900  # 15 minutes for planner
  memory_size = 2048 # 2GB for planner

  environment {
    variables = {
      AURORA_CLUSTER_ARN = var.aurora_cluster_arn
      AURORA_SECRET_ARN  = var.aurora_secret_arn
      AURORA_DATABASE    = var.name_prefix
      VECTOR_BUCKET      = var.vector_bucket
      BEDROCK_MODEL_ID   = var.bedrock_model_id
      BEDROCK_REGION     = var.bedrock_region
      DEFAULT_AWS_REGION = var.aws_region
      AUDIT_BUCKET       = local.audit_bucket
      SAGEMAKER_ENDPOINT = local.sagemaker_endpoint
      # The agents it calls
      TAGGER_FUNCTION     = "${var.name_prefix}-tagger"
      REPORTER_FUNCTION   = "${var.name_prefix}-reporter"
      CHARTER_FUNCTION    = "${var.name_prefix}-charter"
      RETIREMENT_FUNCTION = "${var.name_prefix}-retirement"
      # LangFuse observability (optional)
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_HOST       = var.langfuse_host
      OPENAI_API_KEY      = var.openai_api_key
    }
  }

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = "orchestrator"
  }

  depends_on = [aws_s3_object.lambda_packages["planner"]]
}

# SQS trigger for Planner
resource "aws_lambda_event_source_mapping" "planner_sqs" {
  event_source_arn = aws_sqs_queue.analysis_jobs.arn
  function_name    = aws_lambda_function.planner.arn
  batch_size       = 1
}

# Tagger Lambda
resource "aws_lambda_function" "tagger" {
  function_name = "${var.name_prefix}-tagger"
  role          = aws_iam_role.lambda_agents_role.arn

  # Using S3 for deployment package (>50MB)
  s3_bucket        = aws_s3_bucket.lambda_packages.id
  s3_key           = aws_s3_object.lambda_packages["tagger"].key
  source_code_hash = fileexists("${path.module}/../../backend/tagger/tagger_lambda.zip") ? filebase64sha256("${path.module}/../../backend/tagger/tagger_lambda.zip") : null

  handler     = "lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 300 # 5 minutes for tagger
  memory_size = 1024

  environment {
    variables = {
      AURORA_CLUSTER_ARN = var.aurora_cluster_arn
      AURORA_SECRET_ARN  = var.aurora_secret_arn
      AURORA_DATABASE    = var.name_prefix
      BEDROCK_MODEL_ID   = var.bedrock_model_id
      BEDROCK_REGION     = var.bedrock_region
      DEFAULT_AWS_REGION = var.aws_region
      AUDIT_BUCKET       = local.audit_bucket
      # LangFuse observability (optional)
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_HOST       = var.langfuse_host
      OPENAI_API_KEY      = var.openai_api_key
    }
  }

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = "tagger"
  }

  depends_on = [aws_s3_object.lambda_packages["tagger"]]
}

# Reporter Lambda
resource "aws_lambda_function" "reporter" {
  function_name = "${var.name_prefix}-reporter"
  role          = aws_iam_role.lambda_agents_role.arn

  # Using S3 for deployment package (>50MB)
  s3_bucket        = aws_s3_bucket.lambda_packages.id
  s3_key           = aws_s3_object.lambda_packages["reporter"].key
  source_code_hash = fileexists("${path.module}/../../backend/reporter/reporter_lambda.zip") ? filebase64sha256("${path.module}/../../backend/reporter/reporter_lambda.zip") : null

  handler     = "lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 300 # 5 minutes for reporter agent
  memory_size = 1024

  environment {
    variables = {
      AURORA_CLUSTER_ARN  = var.aurora_cluster_arn
      AURORA_SECRET_ARN   = var.aurora_secret_arn
      AURORA_DATABASE     = var.name_prefix
      BEDROCK_MODEL_ID    = var.bedrock_model_id
      BEDROCK_REGION      = var.bedrock_region
      DEFAULT_AWS_REGION  = var.aws_region
      AUDIT_BUCKET        = local.audit_bucket
      SAGEMAKER_ENDPOINT  = local.sagemaker_endpoint
      VECTOR_BUCKET       = var.vector_bucket
      KB_INDEX_NAME       = var.kb_index_name
      COMPLIANCE_FUNCTION = aws_lambda_function.compliance.function_name
      # LangFuse observability (optional)
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_HOST       = var.langfuse_host
      OPENAI_API_KEY      = var.openai_api_key
    }
  }

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = "reporter"
  }

  depends_on = [aws_s3_object.lambda_packages["reporter"]]
}

# Charter Lambda
resource "aws_lambda_function" "charter" {
  function_name = "${var.name_prefix}-charter"
  role          = aws_iam_role.lambda_agents_role.arn

  # Using S3 for deployment package (>50MB)
  s3_bucket        = aws_s3_bucket.lambda_packages.id
  s3_key           = aws_s3_object.lambda_packages["charter"].key
  source_code_hash = fileexists("${path.module}/../../backend/charter/charter_lambda.zip") ? filebase64sha256("${path.module}/../../backend/charter/charter_lambda.zip") : null

  handler     = "lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 300 # 5 minutes for charter agent
  memory_size = 1024

  environment {
    variables = {
      AURORA_CLUSTER_ARN = var.aurora_cluster_arn
      AURORA_SECRET_ARN  = var.aurora_secret_arn
      AURORA_DATABASE    = var.name_prefix
      BEDROCK_MODEL_ID   = var.bedrock_model_id
      BEDROCK_REGION     = var.bedrock_region
      DEFAULT_AWS_REGION = var.aws_region
      AUDIT_BUCKET       = local.audit_bucket
      # LangFuse observability (optional)
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_HOST       = var.langfuse_host
      OPENAI_API_KEY      = var.openai_api_key
    }
  }

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = "charter"
  }

  depends_on = [aws_s3_object.lambda_packages["charter"]]
}

# Retirement Lambda
resource "aws_lambda_function" "retirement" {
  function_name = "${var.name_prefix}-retirement"
  role          = aws_iam_role.lambda_agents_role.arn

  # Using S3 for deployment package (>50MB)
  s3_bucket        = aws_s3_bucket.lambda_packages.id
  s3_key           = aws_s3_object.lambda_packages["retirement"].key
  source_code_hash = fileexists("${path.module}/../../backend/retirement/retirement_lambda.zip") ? filebase64sha256("${path.module}/../../backend/retirement/retirement_lambda.zip") : null

  handler     = "lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 300 # 5 minutes for retirement agent
  memory_size = 1024

  environment {
    variables = {
      AURORA_CLUSTER_ARN  = var.aurora_cluster_arn
      AURORA_SECRET_ARN   = var.aurora_secret_arn
      AURORA_DATABASE     = var.name_prefix
      BEDROCK_MODEL_ID    = var.bedrock_model_id
      BEDROCK_REGION      = var.bedrock_region
      DEFAULT_AWS_REGION  = var.aws_region
      AUDIT_BUCKET        = local.audit_bucket
      COMPLIANCE_FUNCTION = aws_lambda_function.compliance.function_name
      # LangFuse observability (optional)
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_HOST       = var.langfuse_host
      OPENAI_API_KEY      = var.openai_api_key
    }
  }

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = "retirement"
  }

  depends_on = [aws_s3_object.lambda_packages["retirement"]]
}

# Compliance Checker Lambda: reviews Reporter and Retirement narratives
# before they are saved. Structured output only; no database access.
resource "aws_lambda_function" "compliance" {
  function_name = "${var.name_prefix}-compliance"
  role          = aws_iam_role.lambda_agents_role.arn

  s3_bucket        = aws_s3_bucket.lambda_packages.id
  s3_key           = aws_s3_object.lambda_packages["compliance"].key
  source_code_hash = fileexists("${path.module}/../../backend/compliance/compliance_lambda.zip") ? filebase64sha256("${path.module}/../../backend/compliance/compliance_lambda.zip") : null

  handler     = "lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 120 # one short structured-output call, with retries
  memory_size = 1024

  environment {
    variables = {
      BEDROCK_MODEL_ID   = var.bedrock_model_id
      BEDROCK_REGION     = var.bedrock_region
      DEFAULT_AWS_REGION = var.aws_region
      AUDIT_BUCKET       = local.audit_bucket
      # LangFuse observability (optional)
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_HOST       = var.langfuse_host
      OPENAI_API_KEY      = var.openai_api_key
    }
  }

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = "compliance"
  }

  depends_on = [aws_s3_object.lambda_packages["compliance"]]
}

# Signals Lambda: the one shared daily market note (plan section 8.4).
# Started by samruddhi-market-eod (terraform/10_market) after each daily run.
resource "aws_lambda_function" "signals" {
  function_name = "${var.name_prefix}-signals"
  role          = aws_iam_role.lambda_agents_role.arn

  s3_bucket        = aws_s3_bucket.lambda_packages.id
  s3_key           = aws_s3_object.lambda_packages["signals"].key
  source_code_hash = fileexists("${path.module}/../../backend/signals/signals_lambda.zip") ? filebase64sha256("${path.module}/../../backend/signals/signals_lambda.zip") : null

  handler     = "lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 300 # one structured-output call, a possible rewrite and the Compliance Checker
  memory_size = 1024

  environment {
    variables = {
      AURORA_CLUSTER_ARN  = var.aurora_cluster_arn
      AURORA_SECRET_ARN   = var.aurora_secret_arn
      AURORA_DATABASE     = var.name_prefix
      BEDROCK_MODEL_ID    = var.bedrock_model_id
      BEDROCK_REGION      = var.bedrock_region
      DEFAULT_AWS_REGION  = var.aws_region
      AUDIT_BUCKET        = local.audit_bucket
      COMPLIANCE_FUNCTION = aws_lambda_function.compliance.function_name
      # LangFuse observability (optional)
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_HOST       = var.langfuse_host
      OPENAI_API_KEY      = var.openai_api_key
    }
  }

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = "signals"
  }

  depends_on = [aws_s3_object.lambda_packages["signals"]]
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "agent_logs" {
  for_each = toset(["planner", "tagger", "reporter", "charter", "retirement", "compliance", "signals"])

  name              = "/aws/lambda/${var.name_prefix}-${each.key}"
  retention_in_days = 7

  tags = {
    Project = var.name_prefix
    Part    = "6"
    Agent   = each.key
  }
}
