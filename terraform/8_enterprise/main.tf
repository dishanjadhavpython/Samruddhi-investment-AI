# Part 8: Enterprise - CloudWatch Dashboards for Monitoring

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name_prefix = var.name_prefix

  common_tags = {
    Project   = var.name_prefix
    Part      = "8_enterprise"
    ManagedBy = "terraform"
  }
}

# ========================================
# Bedrock & AI Model Usage Dashboard
# ========================================

resource "aws_cloudwatch_dashboard" "ai_model_usage" {
  dashboard_name = "${local.name_prefix}-ai-model-usage"

  dashboard_body = jsonencode({
    widgets = [
      # Bedrock Model Invocations
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "Invocations", "ModelId", var.bedrock_model_id, { stat = "Sum", label = "Model Invocations", id = "m1", color = "#1f77b4" }],
            [".", "InvocationClientErrors", ".", ".", { stat = "Sum", label = "Client Errors", id = "m2", color = "#d62728" }],
            [".", "InvocationServerErrors", ".", ".", { stat = "Sum", label = "Server Errors", id = "m3", color = "#ff7f0e" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.bedrock_region
          title   = "Bedrock Model Invocations (${var.bedrock_model_id})"
          period  = 300
          stat    = "Sum"
          yAxis = {
            left = {
              label     = "Count"
              showUnits = false
            }
          }
        }
      },
      # Bedrock Token Usage
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "InputTokenCount", "ModelId", var.bedrock_model_id, { stat = "Sum", label = "Input Tokens", id = "t1", color = "#2ca02c" }],
            [".", "OutputTokenCount", ".", ".", { stat = "Sum", label = "Output Tokens", id = "t2", color = "#9467bd" }]
          ]
          view    = "timeSeries"
          stacked = true
          region  = var.bedrock_region
          title   = "Bedrock Token Usage (${var.bedrock_model_id})"
          period  = 300
          stat    = "Sum"
          yAxis = {
            left = {
              label     = "Tokens"
              showUnits = false
            }
          }
        }
      },
      # Bedrock Latency
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "InvocationLatency", "ModelId", var.bedrock_model_id, { stat = "Average", label = "Average Latency", id = "l1", color = "#1f77b4" }],
            [".", ".", ".", ".", { stat = "Maximum", label = "Max Latency", id = "l2", color = "#d62728" }],
            [".", ".", ".", ".", { stat = "Minimum", label = "Min Latency", id = "l3", color = "#2ca02c" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.bedrock_region
          title   = "Bedrock Response Latency (${var.bedrock_model_id})"
          period  = 300
          yAxis = {
            left = {
              label     = "Latency (ms)"
              showUnits = false
            }
          }
        }
      },
      # SageMaker Endpoint Invocations
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            [{ expression = "SEARCH(' {AWS/SageMaker,EndpointName,VariantName} MetricName=\"Invocations\" EndpointName=\"${var.name_prefix}-embedding-endpoint\" ', 'Sum')", id = "s1", label = "Invocations", color = "#1f77b4" }],
            [{ expression = "SEARCH(' {AWS/SageMaker,EndpointName,VariantName} MetricName=\"Invocation4XXErrors\" EndpointName=\"${var.name_prefix}-embedding-endpoint\" ', 'Sum')", id = "s2", label = "4XX Errors", color = "#ff7f0e" }],
            [{ expression = "SEARCH(' {AWS/SageMaker,EndpointName,VariantName} MetricName=\"Invocation5XXErrors\" EndpointName=\"${var.name_prefix}-embedding-endpoint\" ', 'Sum')", id = "s3", label = "5XX Errors", color = "#d62728" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "SageMaker Embedding Endpoint Invocations"
          period  = 300
          yAxis = {
            left = {
              label     = "Count"
              showUnits = false
            }
          }
        }
      },
      # SageMaker Model Latency
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            [{ expression = "SEARCH(' {AWS/SageMaker,EndpointName,VariantName} MetricName=\"ModelLatency\" EndpointName=\"${var.name_prefix}-embedding-endpoint\" ', 'Average')", id = "ml1", label = "Average Latency", color = "#2ca02c" }],
            [{ expression = "SEARCH(' {AWS/SageMaker,EndpointName,VariantName} MetricName=\"ModelLatency\" EndpointName=\"${var.name_prefix}-embedding-endpoint\" ', 'Maximum')", id = "ml2", label = "Max Latency", color = "#d62728" }],
            [{ expression = "SEARCH(' {AWS/SageMaker,EndpointName,VariantName} MetricName=\"ModelLatency\" EndpointName=\"${var.name_prefix}-embedding-endpoint\" ', 'Minimum')", id = "ml3", label = "Min Latency", color = "#1f77b4" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "SageMaker Model Latency"
          period  = 300
          yAxis = {
            left = {
              label     = "Latency (μs)"
              showUnits = false
            }
          }
        }
      }
    ]
  })

}

# ========================================
# Agent Performance Dashboard
# ========================================

resource "aws_cloudwatch_dashboard" "agent_performance" {
  dashboard_name = "${local.name_prefix}-agent-performance"

  dashboard_body = jsonencode({
    widgets = [
      # Agent Execution Times
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", "${var.name_prefix}-planner", { stat = "Average", label = "Planner", id = "m1", color = "#1f77b4" }],
            [".", ".", ".", "${var.name_prefix}-reporter", { stat = "Average", label = "Reporter", id = "m2", color = "#2ca02c" }],
            [".", ".", ".", "${var.name_prefix}-charter", { stat = "Average", label = "Charter", id = "m3", color = "#ff7f0e" }],
            [".", ".", ".", "${var.name_prefix}-retirement", { stat = "Average", label = "Retirement", id = "m4", color = "#d62728" }],
            [".", ".", ".", "${var.name_prefix}-tagger", { stat = "Average", label = "Tagger", id = "m5", color = "#9467bd" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Agent Execution Times"
          period  = 300
          stat    = "Average"
          yAxis = {
            left = {
              label     = "Duration (ms)"
              showUnits = false
            }
          }
        }
      },
      # Agent Error Rates
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", "${var.name_prefix}-planner", { stat = "Sum", label = "Planner Errors", id = "e1", color = "#1f77b4" }],
            [".", ".", ".", "${var.name_prefix}-reporter", { stat = "Sum", label = "Reporter Errors", id = "e2", color = "#2ca02c" }],
            [".", ".", ".", "${var.name_prefix}-charter", { stat = "Sum", label = "Charter Errors", id = "e3", color = "#ff7f0e" }],
            [".", ".", ".", "${var.name_prefix}-retirement", { stat = "Sum", label = "Retirement Errors", id = "e4", color = "#d62728" }],
            [".", ".", ".", "${var.name_prefix}-tagger", { stat = "Sum", label = "Tagger Errors", id = "e5", color = "#9467bd" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Agent Error Rates"
          period  = 300
          stat    = "Sum"
          yAxis = {
            left = {
              label     = "Error Count"
              showUnits = false
            }
          }
        }
      },
      # Agent Invocations
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", "${var.name_prefix}-planner", { stat = "Sum", label = "Planner", id = "i1", color = "#1f77b4" }],
            [".", ".", ".", "${var.name_prefix}-reporter", { stat = "Sum", label = "Reporter", id = "i2", color = "#2ca02c" }],
            [".", ".", ".", "${var.name_prefix}-charter", { stat = "Sum", label = "Charter", id = "i3", color = "#ff7f0e" }],
            [".", ".", ".", "${var.name_prefix}-retirement", { stat = "Sum", label = "Retirement", id = "i4", color = "#d62728" }],
            [".", ".", ".", "${var.name_prefix}-tagger", { stat = "Sum", label = "Tagger", id = "i5", color = "#9467bd" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Agent Invocation Counts"
          period  = 300
          stat    = "Sum"
          yAxis = {
            left = {
              label     = "Invocation Count"
              showUnits = false
            }
          }
        }
      },
      # Concurrent Executions
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "ConcurrentExecutions", "FunctionName", "${var.name_prefix}-planner", { stat = "Maximum", label = "Planner", id = "c1", color = "#1f77b4" }],
            [".", ".", ".", "${var.name_prefix}-reporter", { stat = "Maximum", label = "Reporter", id = "c2", color = "#2ca02c" }],
            [".", ".", ".", "${var.name_prefix}-charter", { stat = "Maximum", label = "Charter", id = "c3", color = "#ff7f0e" }],
            [".", ".", ".", "${var.name_prefix}-retirement", { stat = "Maximum", label = "Retirement", id = "c4", color = "#d62728" }],
            [".", ".", ".", "${var.name_prefix}-tagger", { stat = "Maximum", label = "Tagger", id = "c5", color = "#9467bd" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Concurrent Executions"
          period  = 300
          stat    = "Maximum"
          yAxis = {
            left = {
              label     = "Concurrent Executions"
              showUnits = false
            }
          }
        }
      },
      # Throttles
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Throttles", "FunctionName", "${var.name_prefix}-planner", { stat = "Sum", label = "Planner Throttles", id = "t1", color = "#1f77b4" }],
            [".", ".", ".", "${var.name_prefix}-reporter", { stat = "Sum", label = "Reporter Throttles", id = "t2", color = "#2ca02c" }],
            [".", ".", ".", "${var.name_prefix}-charter", { stat = "Sum", label = "Charter Throttles", id = "t3", color = "#ff7f0e" }],
            [".", ".", ".", "${var.name_prefix}-retirement", { stat = "Sum", label = "Retirement Throttles", id = "t4", color = "#d62728" }],
            [".", ".", ".", "${var.name_prefix}-tagger", { stat = "Sum", label = "Tagger Throttles", id = "t5", color = "#9467bd" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Agent Throttles"
          period  = 300
          stat    = "Sum"
          yAxis = {
            left = {
              label     = "Throttle Count"
              showUnits = false
            }
          }
        }
      }
    ]
  })

}
