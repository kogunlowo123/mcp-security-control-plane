terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
  required_version = ">= 1.8"
}

locals {
  common_tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

data "aws_caller_identity" "current" {}

# Corpus bucket for MCP security documents
resource "aws_s3_bucket" "corpus" {
  bucket        = "${var.project_name}-${var.environment}-corpus-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment != "prod"
  tags          = merge(local.common_tags, { Purpose = "rag-corpus" })
}

resource "aws_s3_bucket_versioning" "corpus" {
  bucket = aws_s3_bucket.corpus.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "corpus" {
  bucket = aws_s3_bucket.corpus.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.s3_kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "corpus" {
  bucket                  = aws_s3_bucket.corpus.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "corpus" {
  bucket = aws_s3_bucket.corpus.id
  rule {
    id     = "transition-old-versions"
    status = "Enabled"
    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }
    noncurrent_version_expiration { noncurrent_days = 365 }
  }
}

# Audit logs bucket
resource "aws_s3_bucket" "audit_logs" {
  bucket        = "${var.project_name}-${var.environment}-audit-logs-${data.aws_caller_identity.current.account_id}"
  force_destroy = false
  tags          = merge(local.common_tags, { Purpose = "audit-logs" })
}

resource "aws_s3_bucket_versioning" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.s3_kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "audit_logs" {
  bucket                  = aws_s3_bucket.audit_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  rule {
    id     = "audit-retention"
    status = "Enabled"
    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 365
      storage_class = "GLACIER"
    }
    expiration { days = 2555 }  # 7 years retention
  }
}
