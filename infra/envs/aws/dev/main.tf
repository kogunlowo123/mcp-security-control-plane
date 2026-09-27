terraform {
  required_version = ">= 1.8"
  backend "s3" {
    bucket         = "mcp-security-control-plane-tfstate"
    key            = "aws/dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mcp-security-control-plane-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "mcp-security-control-plane"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}

module "kms" {
  source       = "../../../aws/kms"
  project_name = "mcp-security-control-plane"
  environment  = "dev"
}

module "network" {
  source              = "../../../aws/network"
  project_name        = "mcp-security-control-plane"
  environment         = "dev"
  vpc_cidr            = "10.0.0.0/16"
  single_nat_gateway  = true
}

module "eks" {
  source             = "../../../aws/eks"
  project_name       = "mcp-security-control-plane"
  environment        = "dev"
  vpc_id             = module.network.vpc_id
  subnet_ids         = module.network.private_subnet_ids
  kms_key_arn        = module.kms.platform_key_arn
  node_group_min     = 2
  node_group_max     = 5
  node_group_desired = 2
}

module "aurora" {
  source              = "../../../aws/aurora-pgvector"
  project_name        = "mcp-security-control-plane"
  environment         = "dev"
  vpc_id              = module.network.vpc_id
  subnet_ids          = module.network.private_subnet_ids
  kms_key_arn         = module.kms.db_key_arn
  allowed_cidr_blocks = [module.network.vpc_cidr]
  deletion_protection = false
}

module "opensearch" {
  source              = "../../../aws/opensearch"
  project_name        = "mcp-security-control-plane"
  environment         = "dev"
  vpc_id              = module.network.vpc_id
  subnet_ids          = module.network.private_subnet_ids
  allowed_cidr_blocks = [module.network.vpc_cidr]
  kms_key_arn         = module.kms.platform_key_arn
}

module "s3" {
  source         = "../../../aws/s3"
  project_name   = "mcp-security-control-plane"
  environment    = "dev"
  s3_kms_key_arn = module.kms.s3_key_arn
}

module "sqs" {
  source       = "../../../aws/sqs"
  project_name = "mcp-security-control-plane"
  environment  = "dev"
  kms_key_arn  = module.kms.platform_key_arn
}

module "iam" {
  source             = "../../../aws/iam"
  project_name       = "mcp-security-control-plane"
  environment        = "dev"
  oidc_provider_arn  = module.eks.oidc_provider_arn
  oidc_provider_url  = module.eks.cluster_oidc_issuer_url
  sqs_queue_arns     = [module.sqs.mcp_events_queue_arn, module.sqs.mcp_violations_queue_arn]
  s3_bucket_arns     = [module.s3.corpus_bucket_arn, module.s3.audit_logs_bucket_arn]
  kms_key_arns       = [module.kms.platform_key_arn, module.kms.db_key_arn, module.kms.s3_key_arn]
}
