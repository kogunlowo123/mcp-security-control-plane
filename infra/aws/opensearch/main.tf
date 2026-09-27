terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
  required_version = ">= 1.8"
}

locals {
  domain_name = "${var.project_name}-${var.environment}"
  common_tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_security_group" "opensearch" {
  name        = "${local.domain_name}-opensearch-sg"
  description = "Security group for OpenSearch domain"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
    description = "HTTPS from allowed CIDRs"
  }

  tags = local.common_tags
}

resource "aws_opensearch_domain" "main" {
  domain_name    = local.domain_name
  engine_version = "OpenSearch_2.11"

  cluster_config {
    instance_count           = var.environment == "prod" ? 3 : 1
    instance_type            = var.environment == "prod" ? "r6g.large.search" : "t3.small.search"
    dedicated_master_enabled = var.environment == "prod"
    dedicated_master_count   = var.environment == "prod" ? 3 : 0
    dedicated_master_type    = var.environment == "prod" ? "m6g.large.search" : null
    zone_awareness_enabled   = var.environment == "prod"

    dynamic "zone_awareness_config" {
      for_each = var.environment == "prod" ? [1] : []
      content {
        availability_zone_count = 3
      }
    }
  }

  vpc_options {
    subnet_ids         = var.environment == "prod" ? var.subnet_ids : [var.subnet_ids[0]]
    security_group_ids = [aws_security_group.opensearch.id]
  }

  ebs_options {
    ebs_enabled = true
    volume_size = var.environment == "prod" ? 100 : 20
    volume_type = "gp3"
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = var.kms_key_arn
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  advanced_security_options {
    enabled                        = true
    anonymous_auth_enabled         = false
    internal_user_database_enabled = false

    master_user_options {
      master_user_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
    }
  }

  auto_tune_options {
    desired_state = "ENABLED"
    rollback_on_disable = "NO_ROLLBACK"
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
      Action    = "es:*"
      Resource  = "arn:aws:es:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:domain/${local.domain_name}/*"
    }]
  })

  tags = local.common_tags
}
