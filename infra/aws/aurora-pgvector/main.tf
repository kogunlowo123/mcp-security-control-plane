terraform {
  required_providers {
    aws    = { source = "hashicorp/aws", version = ">= 5.0" }
    random = { source = "hashicorp/random", version = ">= 3.0" }
  }
  required_version = ">= 1.8"
}

locals {
  cluster_id  = "${var.project_name}-${var.environment}-aurora"
  common_tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

# Random password for the master user
resource "random_password" "master" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# Store password in Secrets Manager
resource "aws_secretsmanager_secret" "aurora_master" {
  name                    = "${local.cluster_id}-master-password"
  description             = "Aurora master user password for ${local.cluster_id}"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "aurora_master" {
  secret_id = aws_secretsmanager_secret.aurora_master.id
  secret_string = jsonencode({
    username = "mcpadmin"
    password = random_password.master.result
    host     = aws_rds_cluster.main.endpoint
    port     = 5432
    dbname   = var.database_name
  })
}

# DB Subnet Group
resource "aws_db_subnet_group" "main" {
  name        = "${local.cluster_id}-subnet-group"
  subnet_ids  = var.subnet_ids
  description = "Subnet group for ${local.cluster_id}"
  tags        = local.common_tags
}

# Security Group
resource "aws_security_group" "aurora" {
  name        = "${local.cluster_id}-sg"
  description = "Security group for Aurora PostgreSQL cluster"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
    description = "PostgreSQL from allowed CIDR blocks"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

# Parameter Group with pgvector enabled
resource "aws_rds_cluster_parameter_group" "main" {
  name        = "${local.cluster_id}-params"
  family      = "aurora-postgresql16"
  description = "Aurora PostgreSQL parameters with pgvector"

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements,vector"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  tags = local.common_tags
}

# Aurora PostgreSQL Serverless v2 Cluster
resource "aws_rds_cluster" "main" {
  cluster_identifier      = local.cluster_id
  engine                  = "aurora-postgresql"
  engine_version          = "16.1"
  database_name           = var.database_name
  master_username         = "mcpadmin"
  master_password         = random_password.master.result
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.aurora.id]
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.main.name

  storage_encrypted   = true
  kms_key_id          = var.kms_key_arn
  deletion_protection = var.deletion_protection

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 8.0
  }

  backup_retention_period      = var.environment == "prod" ? 14 : 7
  preferred_backup_window      = "03:00-04:00"
  preferred_maintenance_window = "sun:04:00-sun:05:00"

  enabled_cloudwatch_logs_exports = ["postgresql"]

  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${local.cluster_id}-final" : null

  tags = local.common_tags
}

# Aurora Serverless v2 instance
resource "aws_rds_cluster_instance" "main" {
  count              = var.environment == "prod" ? 2 : 1
  identifier         = "${local.cluster_id}-instance-${count.index}"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version

  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.rds_monitoring.arn

  tags = local.common_tags
}

# IAM role for enhanced monitoring
resource "aws_iam_role" "rds_monitoring" {
  name = "${local.cluster_id}-rds-monitoring"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
