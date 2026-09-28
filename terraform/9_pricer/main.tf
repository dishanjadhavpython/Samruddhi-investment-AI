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
  # Phase 5 tables, created by terraform/10_market under the same prefix
  market_latest_table   = "${var.name_prefix}-market-latest"
  market_intraday_table = "${var.name_prefix}-market-intraday"

  # Safety toggle: the EventBridge schedule (and its supporting IAM) only get
  # created when this is explicitly flipped to true. The Lambda itself is
  # always created so it can be invoked manually/for testing, but a plain
  # `terraform apply` with defaults leaves it un-triggered and costing nothing.
  scheduler_active = var.enable_scheduler

  # All times IST, Mon-Fri. The NSE cash session is 09:15-15:30 and prices are
  # shown 15 minutes delayed, so the last bar (15:25-15:30) appears at 15:45.
  # One EventBridge cron can't express that range, so intraday is three
  # windows, every 5 minutes. Exchange holidays aren't excluded yet; on those
  # days the price just doesn't change. The mode is passed to the handler.
  pricer_schedules = {
    open  = { cron = "cron(15,20,25,30,35,40,45,50,55 9 ? * MON-FRI *)", mode = "intraday" }   # 09:15 to 09:55
    day   = { cron = "cron(0/5 10-14 ? * MON-FRI *)", mode = "intraday" }                      # 10:00 to 14:55
    close = { cron = "cron(0,5,10,15,20,25,30,35,40,45 15 ? * MON-FRI *)", mode = "intraday" } # 15:00 to 15:45
    eod   = { cron = "cron(15 16 ? * MON-FRI *)", mode = "eod" }                               # final bars, NAVs, snapshots
    nav   = { cron = "cron(30 23 ? * MON-FRI *)", mode = "nav" }                               # AMFI publishes by 23:00
  }
}

# ========================================
# IAM Role for the Pricer Lambda
# ========================================

resource "aws_iam_role" "pricer_lambda_role" {
  name = "${var.name_prefix}-pricer-lambda-role"

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
    Part    = "9"
  }
}

resource "aws_iam_role_policy" "pricer_lambda_policy" {
  name = "${var.name_prefix}-pricer-lambda-policy"
  role = aws_iam_role.pricer_lambda_role.id

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
      # Aurora Data API access - refresh instrument prices
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
      # Delayed prices for GET /api/market/snapshot (tables in terraform/10_market)
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:BatchWriteItem"
        ]
        Resource = [
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.market_latest_table}",
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.market_intraday_table}"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "pricer_lambda_basic" {
  role       = aws_iam_role.pricer_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ========================================
# S3 Bucket for the Pricer Lambda Package
# ========================================

# Independent directory, so this doesn't assume the Part 6 lambda_packages
# bucket exists in the same apply - it gets its own.
resource "aws_s3_bucket" "lambda_packages" {
  bucket = "${var.name_prefix}-pricer-lambda-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project = var.name_prefix
    Part    = "9"
  }
}

resource "aws_s3_object" "pricer_package" {
  bucket = aws_s3_bucket.lambda_packages.id
  key    = "pricer/pricer_lambda.zip"
  source = "${path.module}/../../backend/pricer/pricer_lambda.zip"
  etag   = fileexists("${path.module}/../../backend/pricer/pricer_lambda.zip") ? filemd5("${path.module}/../../backend/pricer/pricer_lambda.zip") : null

  tags = {
    Project = var.name_prefix
    Part    = "9"
  }
}

# ========================================
# Pricer Lambda Function
# ========================================

resource "aws_lambda_function" "pricer" {
  function_name = "${var.name_prefix}-pricer"
  role          = aws_iam_role.pricer_lambda_role.arn

  # Using S3 for deployment package (yfinance pulls in pandas/numpy, >50MB)
  s3_bucket        = aws_s3_bucket.lambda_packages.id
  s3_key           = aws_s3_object.pricer_package.key
  source_code_hash = fileexists("${path.module}/../../backend/pricer/pricer_lambda.zip") ? filebase64sha256("${path.module}/../../backend/pricer/pricer_lambda.zip") : null

  handler     = "lambda_handler.handler"
  runtime     = "python3.12"
  timeout     = 180 # one batched Yahoo download, plus the AMFI NAV file on eod/nav runs
  memory_size = 1024

  environment {
    variables = {
      AURORA_CLUSTER_ARN = var.aurora_cluster_arn
      AURORA_SECRET_ARN  = var.aurora_secret_arn
      AURORA_DATABASE    = var.aurora_database
      DEFAULT_AWS_REGION = var.aws_region

      MARKET_LATEST_TABLE    = local.market_latest_table
      MARKET_INTRADAY_TABLE  = local.market_intraday_table
      SNAPSHOT_DELAY_MINUTES = var.snapshot_delay_minutes
    }
  }

  tags = {
    Project = var.name_prefix
    Part    = "9"
    Agent   = "pricer"
  }

  depends_on = [aws_s3_object.pricer_package]
}

resource "aws_cloudwatch_log_group" "pricer_logs" {
  name              = "/aws/lambda/${var.name_prefix}-pricer"
  retention_in_days = 7

  tags = {
    Project = var.name_prefix
    Part    = "9"
  }
}

# ========================================
# EventBridge Schedule (NSE session hours, IST) - gated behind enable_scheduler
# ========================================

# IAM role for EventBridge Scheduler to invoke the Pricer Lambda
resource "aws_iam_role" "eventbridge_role" {
  count = local.scheduler_active ? 1 : 0
  name  = "${var.name_prefix}-pricer-eventbridge-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Project = var.name_prefix
    Part    = "9"
  }
}

resource "aws_iam_role_policy" "eventbridge_invoke_lambda" {
  count = local.scheduler_active ? 1 : 0
  name  = "InvokePricerLambdaPolicy"
  role  = aws_iam_role.eventbridge_role[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.pricer.arn
      }
    ]
  })
}

resource "aws_scheduler_schedule" "pricer_schedule" {
  for_each = local.scheduler_active ? local.pricer_schedules : {}
  name     = "${var.name_prefix}-pricer-${each.key}"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = each.value.cron
  schedule_expression_timezone = "Asia/Kolkata"

  target {
    arn      = aws_lambda_function.pricer.arn
    role_arn = aws_iam_role.eventbridge_role[0].arn
    input    = jsonencode({ mode = each.value.mode })
  }
}

resource "aws_lambda_permission" "allow_eventbridge" {
  for_each      = aws_scheduler_schedule.pricer_schedule
  statement_id  = "AllowExecutionFromEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pricer.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = each.value.arn
}
