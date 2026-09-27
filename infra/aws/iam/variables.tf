variable "project_name"     { type = string }
variable "environment"      { type = string }
variable "oidc_provider_arn" { type = string }
variable "oidc_provider_url" { type = string }
variable "sqs_queue_arns"   { type = list(string); default = [] }
variable "s3_bucket_arns"   { type = list(string); default = [] }
variable "bedrock_model_arns" { type = list(string); default = ["arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0", "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0"] }
variable "kms_key_arns"     { type = list(string); default = [] }

variable "api_service_account" {
  type = object({ namespace = string, name = string })
  default = { namespace = "mcp-security", name = "mcp-api" }
}

variable "agent_runtime_service_account" {
  type = object({ namespace = string, name = string })
  default = { namespace = "mcp-security", name = "mcp-agent-runtime" }
}

variable "rag_core_service_account" {
  type = object({ namespace = string, name = string })
  default = { namespace = "mcp-security", name = "mcp-rag-core" }
}

variable "tags" { type = map(string); default = {} }
