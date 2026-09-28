variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "sagemaker_image_uri" {
  description = "Optional override for the SageMaker container image URI"
  type        = string
  default     = null
}

variable "embedding_model_name" {
  description = "Name of the HuggingFace model to use"
  type        = string
  default     = "sentence-transformers/all-MiniLM-L6-v2"
}

variable "name_prefix" {
  description = "Prefix for every resource name. New deployments use \"samruddhi\"; an existing deployment keeps the prefix it was created with (set it in terraform.tfvars)."
  type        = string
  default     = "samruddhi"
}
