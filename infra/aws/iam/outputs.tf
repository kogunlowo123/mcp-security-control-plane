output "api_service_role_arn"           { value = aws_iam_role.api_service.arn }
output "agent_runtime_role_arn"         { value = aws_iam_role.agent_runtime.arn }
output "rag_core_role_arn"              { value = aws_iam_role.rag_core.arn }
