output "mcp_events_queue_url"  { value = aws_sqs_queue.mcp_events.url }
output "mcp_events_queue_arn"  { value = aws_sqs_queue.mcp_events.arn }
output "mcp_violations_queue_url" { value = aws_sqs_queue.mcp_violations.url }
output "mcp_violations_queue_arn" { value = aws_sqs_queue.mcp_violations.arn }
