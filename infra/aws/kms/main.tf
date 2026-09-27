terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
  required_version = ">= 1.8"
}

locals {
  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Platform KMS key (general purpose)
resource "aws_kms_key" "platform" {
  description             = "${var.project_name}-${var.environment} platform encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "Enable IAM User Permissions"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      }
    ]
  })

  tags = merge(local.common_tags, { Name = "${var.project_name}-${var.environment}-platform-key" })
}

resource "aws_kms_alias" "platform" {
  name          = "alias/${var.project_name}-${var.environment}-platform"
  target_key_id = aws_kms_key.platform.key_id
}

# DB KMS key
resource "aws_kms_key" "db" {
  description             = "${var.project_name}-${var.environment} database encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "Enable IAM Permissions"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      }
    ]
  })

  tags = merge(local.common_tags, { Name = "${var.project_name}-${var.environment}-db-key" })
}

resource "aws_kms_alias" "db" {
  name          = "alias/${var.project_name}-${var.environment}-db"
  target_key_id = aws_kms_key.db.key_id
}

# S3 KMS key
resource "aws_kms_key" "s3" {
  description             = "${var.project_name}-${var.environment} S3 encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "Enable IAM Permissions"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      }
    ]
  })

  tags = merge(local.common_tags, { Name = "${var.project_name}-${var.environment}-s3-key" })
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${var.project_name}-${var.environment}-s3"
  target_key_id = aws_kms_key.s3.key_id
}
