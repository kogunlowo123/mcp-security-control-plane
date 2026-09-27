terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
  required_version = ">= 1.8"
}

locals {
  common_tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

# DLQ for mcp-events
resource "aws_sqs_queue" "mcp_events_dlq" {
  name                       = "${var.project_name}-${var.environment}-mcp-events-dlq"
  message_retention_seconds  = 1209600  # 14 days
  kms_master_key_id          = var.kms_key_arn
  tags                       = local.common_tags
}

# Main mcp-events queue
resource "aws_sqs_queue" "mcp_events" {
  name                       = "${var.project_name}-${var.environment}-mcp-events"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 86400  # 1 day
  kms_master_key_id          = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.mcp_events_dlq.arn
    maxReceiveCount     = 3
  })

  tags = local.common_tags
}

# DLQ for mcp-violations
resource "aws_sqs_queue" "mcp_violations_dlq" {
  name                      = "${var.project_name}-${var.environment}-mcp-violations-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = var.kms_key_arn
  tags                      = local.common_tags
}

# mcp-violations queue
resource "aws_sqs_queue" "mcp_violations" {
  name                       = "${var.project_name}-${var.environment}-mcp-violations"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 259200  # 3 days
  kms_master_key_id          = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.mcp_violations_dlq.arn
    maxReceiveCount     = 5
  })

  tags = local.common_tags
}
