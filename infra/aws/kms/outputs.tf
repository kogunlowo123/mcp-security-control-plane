output "platform_key_arn" { value = aws_kms_key.platform.arn }
output "platform_key_id"  { value = aws_kms_key.platform.key_id }
output "db_key_arn"       { value = aws_kms_key.db.arn }
output "db_key_id"        { value = aws_kms_key.db.key_id }
output "s3_key_arn"       { value = aws_kms_key.s3.arn }
output "s3_key_id"        { value = aws_kms_key.s3.key_id }
