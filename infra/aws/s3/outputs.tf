output "corpus_bucket_name" { value = aws_s3_bucket.corpus.id }
output "corpus_bucket_arn"  { value = aws_s3_bucket.corpus.arn }
output "audit_logs_bucket_name" { value = aws_s3_bucket.audit_logs.id }
output "audit_logs_bucket_arn"  { value = aws_s3_bucket.audit_logs.arn }
