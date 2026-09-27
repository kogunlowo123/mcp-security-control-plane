terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
  required_version = ">= 1.8"
}

locals {
  common_tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

# Helper to build IRSA assume-role policy
data "aws_iam_policy_document" "irsa_assume" {
  for_each = {
    api           = var.api_service_account
    agent_runtime = var.agent_runtime_service_account
    rag_core      = var.rag_core_service_account
  }

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:${each.value.namespace}:${each.value.name}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

# API service role
resource "aws_iam_role" "api_service" {
  name               = "${var.project_name}-${var.environment}-api-service"
  assume_role_policy = data.aws_iam_policy_document.irsa_assume["api"].json
  tags               = local.common_tags
}

resource "aws_iam_policy" "api_service" {
  name = "${var.project_name}-${var.environment}-api-service-policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SQSPublish"
        Effect = "Allow"
        Action = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
        Resource = var.sqs_queue_arns
      },
      {
        Sid    = "S3Read"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = var.bedrock_model_arns
      },
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
        Resource = ["arn:aws:secretsmanager:*:*:secret:${var.project_name}-${var.environment}-*"]
      },
      {
        Sid    = "KMSDecrypt"
        Effect = "Allow"
        Action = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.kms_key_arns
      }
    ]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "api_service" {
  role       = aws_iam_role.api_service.name
  policy_arn = aws_iam_policy.api_service.arn
}

# Agent runtime service role
resource "aws_iam_role" "agent_runtime" {
  name               = "${var.project_name}-${var.environment}-agent-runtime"
  assume_role_policy = data.aws_iam_policy_document.irsa_assume["agent_runtime"].json
  tags               = local.common_tags
}

resource "aws_iam_policy" "agent_runtime" {
  name = "${var.project_name}-${var.environment}-agent-runtime-policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockFull"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:GetFoundationModel"]
        Resource = var.bedrock_model_arns
      },
      {
        Sid    = "SQSReadWrite"
        Effect = "Allow"
        Action = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = var.sqs_queue_arns
      },
      {
        Sid    = "S3ReadWrite"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = ["arn:aws:secretsmanager:*:*:secret:${var.project_name}-${var.environment}-*"]
      },
      {
        Sid    = "KMSDecrypt"
        Effect = "Allow"
        Action = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.kms_key_arns
      }
    ]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "agent_runtime" {
  role       = aws_iam_role.agent_runtime.name
  policy_arn = aws_iam_policy.agent_runtime.arn
}

# RAG core service role
resource "aws_iam_role" "rag_core" {
  name               = "${var.project_name}-${var.environment}-rag-core"
  assume_role_policy = data.aws_iam_policy_document.irsa_assume["rag_core"].json
  tags               = local.common_tags
}

resource "aws_iam_policy" "rag_core" {
  name = "${var.project_name}-${var.environment}-rag-core-policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3CorpusAccess"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Sid    = "BedrockEmbedding"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = var.bedrock_model_arns
      },
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = ["arn:aws:secretsmanager:*:*:secret:${var.project_name}-${var.environment}-*"]
      },
      {
        Sid    = "KMSDecrypt"
        Effect = "Allow"
        Action = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.kms_key_arns
      }
    ]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "rag_core" {
  role       = aws_iam_role.rag_core.name
  policy_arn = aws_iam_policy.rag_core.arn
}
