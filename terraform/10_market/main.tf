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

data "aws_caller_identity" "current" {}

locals {
  package_path = "${path.module}/../../backend/market/market_lambda.zip"

  # Written by other folders under the same prefix
  signals_function      = "${var.name_prefix}-signals" # terraform/6_agents
  ingest_function       = "${var.name_prefix}-ingest"  # terraform/3_ingestion
  market_latest_table   = "${var.name_prefix}-market-latest"
  market_intraday_table = "${var.name_prefix}-market-intraday"
  tags = {
    Project = var.name_prefix
    Part    = "10"
  }
}

# ========================================
# S3 bucket: Lambda package and manual NSE Indices downloads
# ========================================

# incoming/  - drop valuation/TRI files downloaded from niftyindices.com here;
#              the next daily run loads them and moves them to processed/
#              (or rejected/ if they can't be read)
# lambda/    - the deployment package (pandas/numpy make it too big to upload directly)
resource "aws_s3_bucket" "market" {
  bucket = "${var.name_prefix}-market-${data.aws_caller_identity.current.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "market" {
  bucket                  = aws_s3_bucket.market.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "market_package" {
  bucket = aws_s3_bucket.market.id
  key    = "lambda/market_lambda.zip"
  source = local.package_path
  etag   = fileexists(local.package_path) ? filemd5(local.package_path) : null
  tags   = local.tags
}

# ========================================
# IAM role for the market Lambda
# ========================================

resource "aws_iam_role" "market_lambda_role" {
  name = "${var.name_prefix}-market-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
      }
    ]
  })

  tags = local.tags
}

resource "aws_iam_role_policy" "market_lambda_policy" {
  name = "${var.name_prefix}-market-lambda-policy"
  role = aws_iam_role.market_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      # Aurora Data API: market_series, market_signals, market_charts
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
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.aurora_secret_arn
      },
      # Read and move manual downloads between incoming/, processed/ and rejected/
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.market.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.market.arn}/*"
      },
      # Start the daily market note (samruddhi-signals, 6_agents) and send the
      # daily digest to the knowledge base (samruddhi-ingest, 3_ingestion)
      {
        Effect = "Allow"
        Action = ["lambda:InvokeFunction"]
        Resource = [
          "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.signals_function}",
          "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.ingest_function}"
        ]
      }
    ]
  })
}

# ========================================
# market_eod Lambda
# ========================================

resource "aws_lambda_function" "market_eod" {
  function_name = "${var.name_prefix}-market-eod"
  role          = aws_iam_role.market_lambda_role.arn

  s3_bucket        = aws_s3_bucket.market.id
  s3_key           = aws_s3_object.market_package.key
  source_code_hash = fileexists(local.package_path) ? filebase64sha256(local.package_path) : null

  handler     = "lambda_handler.handler"
  runtime     = "python3.12"
  timeout     = 300 # full recompute takes seconds; a {"period": "max"} reload takes longer
  memory_size = 1024

  environment {
    variables = {
      AURORA_CLUSTER_ARN = var.aurora_cluster_arn
      AURORA_SECRET_ARN  = var.aurora_secret_arn
      AURORA_DATABASE    = var.aurora_database
      DEFAULT_AWS_REGION = var.aws_region
      MARKET_BUCKET      = aws_s3_bucket.market.id
      SIGNALS_FUNCTION   = local.signals_function
      INGEST_FUNCTION    = local.ingest_function
    }
  }

  tags = merge(local.tags, { Agent = "market-eod" })

  depends_on = [aws_s3_object.market_package, aws_cloudwatch_log_group.market_logs]
}

resource "aws_cloudwatch_log_group" "market_logs" {
  name              = "/aws/lambda/${var.name_prefix}-market-eod"
  retention_in_days = 14
  tags              = local.tags
}

# ========================================
# Daily schedule, 19:00 IST Mon-Fri - gated behind enable_scheduler
# ========================================

resource "aws_iam_role" "scheduler_role" {
  count = var.enable_scheduler ? 1 : 0
  name  = "${var.name_prefix}-market-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "scheduler.amazonaws.com" }
      }
    ]
  })

  tags = local.tags
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  count = var.enable_scheduler ? 1 : 0
  name  = "InvokeMarketLambdaPolicy"
  role  = aws_iam_role.scheduler_role[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = aws_lambda_function.market_eod.arn
      }
    ]
  })
}

# After the NSE close (15:30) and the pricer's 16:15 end-of-day run. Exchange
# holidays need no special handling: with no new close, the run just
# recomputes the same day.
resource "aws_scheduler_schedule" "market_eod" {
  count = var.enable_scheduler ? 1 : 0
  name  = "${var.name_prefix}-market-eod"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "cron(0 19 ? * MON-FRI *)"
  schedule_expression_timezone = "Asia/Kolkata"

  target {
    arn      = aws_lambda_function.market_eod.arn
    role_arn = aws_iam_role.scheduler_role[0].arn
    input    = jsonencode({})
  }
}

# ========================================
# Phase 5: delayed intraday prices in DynamoDB
# ========================================

# backend/pricer (9_pricer) writes both tables every 5 minutes during the NSE
# session; GET /api/market/snapshot (7_frontend) reads them, so open tabs poll
# without touching Aurora. Layout: backend/database/src/market_live.py.
resource "aws_dynamodb_table" "market_latest" {
  name         = local.market_latest_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "symbol"

  attribute {
    name = "symbol"
    type = "S"
  }

  tags = local.tags
}

resource "aws_dynamodb_table" "market_intraday" {
  name         = local.market_intraday_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "series" # SYMBOL#YYYY-MM-DD
  range_key    = "minute" # minutes after midnight IST at the end of the 5-minute bar

  attribute {
    name = "series"
    type = "S"
  }

  attribute {
    name = "minute"
    type = "N"
  }

  # Points are kept for 7 days
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = local.tags
}
