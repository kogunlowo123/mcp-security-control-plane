variable "project_name" {
  type        = string
  description = "Project name"
}

variable "environment" {
  type        = string
  description = "Environment (dev/staging/prod)"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for Aurora"
}

variable "allowed_cidr_blocks" {
  type        = list(string)
  description = "CIDR blocks allowed to connect to Aurora"
  default     = []
}

variable "kms_key_arn" {
  type        = string
  description = "KMS key ARN for Aurora encryption"
}

variable "database_name" {
  type        = string
  default     = "mcp_security"
  description = "Name of the initial database"
}

variable "deletion_protection" {
  type        = bool
  default     = false
  description = "Enable deletion protection (set true for prod)"
}

variable "tags" {
  type        = map(string)
  default     = {}
}
