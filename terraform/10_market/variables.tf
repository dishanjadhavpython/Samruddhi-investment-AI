variable "aws_region" {
  description = "AWS region for resources (same region as Aurora)"
  type        = string
}

variable "aurora_cluster_arn" {
  description = "ARN of the Aurora cluster from Part 5"
  type        = string
}

variable "aurora_secret_arn" {
  description = "ARN of the Secrets Manager secret from Part 5"
  type        = string
}

variable "aurora_database" {
  description = "Aurora database name"
  type        = string
  default     = "samruddhi"
}

variable "enable_scheduler" {
  description = <<-EOT
    Feature flag for the daily 19:00 IST (Mon-Fri) market run.
    Defaults to false so a plain `terraform apply` deploys the Lambda
    (invokable manually) without scheduling it. Turn it off, or destroy this
    directory, before destroying Aurora.
  EOT
  type        = bool
  default     = false
}

variable "name_prefix" {
  description = "Prefix for every resource name. New deployments use \"samruddhi\"; an existing deployment keeps the prefix it was created with (set it in terraform.tfvars)."
  type        = string
  default     = "samruddhi"
}
