variable "project_name" {
  description = "The instance's project name (name-prefixes every resource)."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev/staging/prod)."
  type        = string
}

variable "plugin_name" {
  description = "This plugin's name — the URL segment."
  type        = string
  default     = "idea-scout"
}

# --- Frontend routing (ADR-0007 / ADR-0018 §2) -------------------------------

variable "cdn_distribution_arn" {
  description = "ARN of the shared CloudFront distribution — the only reader of the frontend bucket."
  type        = string
}

variable "tags" {
  description = "Resource tags."
  type        = map(string)
  default     = {}
}
