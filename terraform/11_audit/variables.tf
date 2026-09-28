variable "aws_region" {
  description = "AWS region for the audit bucket (the same region as the agents)"
  type        = string
}

variable "retention_days" {
  description = "Object Lock retention for each record. At least 365 (DPDP); 1825 (5 years) if registered with SEBI"
  type        = number
  default     = 365
}

variable "lock_mode" {
  description = "GOVERNANCE (an administrator can override) or COMPLIANCE (no one can, until retention ends)"
  type        = string
  default     = "GOVERNANCE"

  validation {
    condition     = contains(["GOVERNANCE", "COMPLIANCE"], var.lock_mode)
    error_message = "lock_mode must be GOVERNANCE or COMPLIANCE."
  }
}

variable "expiry_margin_days" {
  description = "Days after retention ends before lifecycle removes a record"
  type        = number
  default     = 30
}

variable "name_prefix" {
  description = "Prefix for every resource name. New deployments use \"samruddhi\"; an existing deployment keeps the prefix it was created with (set it in terraform.tfvars)."
  type        = string
  default     = "samruddhi"
}
