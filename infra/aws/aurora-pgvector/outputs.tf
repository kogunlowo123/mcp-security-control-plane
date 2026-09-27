output "cluster_endpoint" {
  description = "Writer endpoint for the Aurora cluster"
  value       = aws_rds_cluster.main.endpoint
}

output "reader_endpoint" {
  description = "Reader endpoint for the Aurora cluster"
  value       = aws_rds_cluster.main.reader_endpoint
}

output "database_name" {
  description = "Name of the initial database"
  value       = aws_rds_cluster.main.database_name
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret containing credentials"
  value       = aws_secretsmanager_secret.aurora_master.arn
}

output "security_group_id" {
  description = "ID of the Aurora security group"
  value       = aws_security_group.aurora.id
}
