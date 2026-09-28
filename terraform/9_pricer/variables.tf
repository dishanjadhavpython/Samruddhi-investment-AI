variable "aws_region" {
  description = "AWS region for resources"
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
    Feature flag for the EventBridge schedules that trigger the Pricer Lambda:
    every 5 minutes during the NSE session (09:15-15:45 IST), plus end-of-day
    (16:15) and NAV (23:30) runs, Mon-Fri.
    Defaults to false so a plain `terraform apply` deploys the Lambda
    (invokable manually/for testing) but does NOT start making scheduled
    calls until you explicitly set this to true.
  EOT
  type        = bool
  default     = false
}

variable "snapshot_delay_minutes" {
  description = "Minutes after a 5-minute bar ends before its price is shown (the delayed-data rule)"
  type        = number
  default     = 15
}

variable "name_prefix" {
  description = "Prefix for every resource name. New deployments use \"samruddhi\"; an existing deployment keeps the prefix it was created with (set it in terraform.tfvars)."
  type        = string
  default     = "samruddhi"
}
