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
  tags = {
    Project = var.name_prefix
    Part    = "11"
  }
}

# ========================================
# Append-only audit log of AI runs (plans/realtime-market-intelligence.md, section 8.7)
# ========================================

# Every agent run writes one JSON Lines object here (backend/database/src/audit.py).
# Object Lock keeps each record from being changed or deleted until its
# retention period ends. Kept in its own directory so destroying the agents
# (6_agents) never touches the log.
resource "aws_s3_bucket" "audit" {
  bucket              = "${var.name_prefix}-audit-${data.aws_caller_identity.current.account_id}"
  object_lock_enabled = true

  tags = local.tags
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id

  versioning_configuration {
    status = "Enabled"
  }
}

# GOVERNANCE: an administrator with s3:BypassGovernanceRetention can still
# remove records (for example, to tear the project down). COMPLIANCE: no one
# can, including the root user, until retention ends. Choose COMPLIANCE only
# for a registered, production service.
resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    default_retention {
      mode = var.lock_mode
      days = var.retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.audit]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket = aws_s3_bucket.audit.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Only TLS requests
resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.audit.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.audit]
}

# Records are kept for the retention period plus a margin, then removed
# (DPDP: no longer than needed). Lifecycle can't remove a locked version early.
resource "aws_s3_bucket_lifecycle_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    id     = "expire-after-retention"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = var.retention_days + var.expiry_margin_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.retention_days + var.expiry_margin_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.audit]
}
