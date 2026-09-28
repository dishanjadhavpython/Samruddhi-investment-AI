variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "min_capacity" {
  description = "Minimum capacity for Aurora Serverless v2 (in ACUs)"
  type        = number
  default     = 0.5
}

variable "max_capacity" {
  description = "Maximum capacity for Aurora Serverless v2 (in ACUs)"
  type        = number
  default     = 1
}

variable "name_prefix" {
  description = "Prefix for every resource name. New deployments use \"samruddhi\"; an existing deployment keeps the prefix it was created with (set it in terraform.tfvars)."
  type        = string
  default     = "samruddhi"
}
