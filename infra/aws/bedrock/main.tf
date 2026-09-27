terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
  required_version = ">= 1.8"
}

locals {
  common_tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

# Bedrock model access policy (attached to service roles via IAM module)
resource "aws_iam_policy" "bedrock_invoke" {
  name = "${var.project_name}-${var.environment}-bedrock-invoke"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "InvokeAllowedModels"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0",
        ]
      },
      {
        Sid    = "ListModels"
        Effect = "Allow"
        Action = ["bedrock:ListFoundationModels", "bedrock:GetFoundationModel"]
        Resource = "*"
      }
    ]
  })
  tags = local.common_tags
}
