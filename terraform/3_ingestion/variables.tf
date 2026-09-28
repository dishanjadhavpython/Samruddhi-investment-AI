variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "sagemaker_endpoint_name" {
  description = "Name of the SageMaker endpoint from Part 2"
  type        = string
}
variable "index_name" {
  description = "S3 Vectors index the ingest Lambda writes to (backend/ingest/create_index_v2.py)"
  type        = string
  default     = "financial-research-v2"
}

variable "enable_cleanup_schedule" {
  description = "Delete expired vectors every Sunday at 03:00 IST"
  type        = bool
  default     = true
}

variable "name_prefix" {
  description = "Prefix for every resource name. New deployments use \"samruddhi\"; an existing deployment keeps the prefix it was created with (set it in terraform.tfvars)."
  type        = string
  default     = "samruddhi"
}
