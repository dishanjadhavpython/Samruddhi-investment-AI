variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "openai_api_key" {
  description = "OpenAI API key for the researcher agent"
  type        = string
  sensitive   = true
}

variable "ingest_api_endpoint" {
  description = "Samruddhi API endpoint from Part 3"
  type        = string
}

variable "ingest_api_key" {
  description = "Samruddhi API key from Part 3"
  type        = string
  sensitive   = true
}

variable "scheduler_enabled" {
  description = "Enable automated research scheduler"
  type        = bool
  default     = false
}

variable "researcher_image_uri" {
  description = "Full ECR image URI for the researcher Lambda container"
  type        = string
  default     = ""
}

variable "bedrock_region" {
  description = "AWS region used for Bedrock model inference"
  type        = string
  default     = "us-west-2"
}

variable "researcher_model" {
  description = "Bedrock model identifier used by the researcher; must support tools and MCP"
  type        = string
  default     = "bedrock/us.amazon.nova-pro-v1:0"
}

variable "mcp_logging" {
  description = "Set to exact string True to enable researcher MCP logging"
  type        = string
  default     = "False"
}

variable "playwright_mcp_timeout_seconds" {
  description = "Timeout for the Playwright MCP client session"
  type        = number
  default     = 300
}

variable "research_schedule" {
  description = "When the scheduler starts a research run (EventBridge Scheduler expression)"
  type        = string
  default     = "rate(2 hours)"
}

variable "research_schedule_timezone" {
  description = "Time zone for research_schedule when it is a cron expression"
  type        = string
  default     = "UTC"
}

variable "name_prefix" {
  description = "Prefix for every resource name. New deployments use \"samruddhi\"; an existing deployment keeps the prefix it was created with (set it in terraform.tfvars)."
  type        = string
  default     = "samruddhi"
}
