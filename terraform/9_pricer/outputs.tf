output "pricer_function_name" {
  description = "Name of the Pricer Lambda function"
  value       = aws_lambda_function.pricer.function_name
}

output "pricer_function_arn" {
  description = "ARN of the Pricer Lambda function"
  value       = aws_lambda_function.pricer.arn
}

output "scheduler_status" {
  description = "Status of the NSE-session price schedule"
  value       = var.enable_scheduler ? "Enabled - every 15 minutes 09:15-15:30 IST, plus eod 16:15 and nav 23:30 IST, Mon-Fri" : "Disabled - set enable_scheduler = true to activate"
}

output "schedule_arns" {
  description = "ARNs of the EventBridge schedules (empty when enable_scheduler = false)"
  value       = { for name, schedule in aws_scheduler_schedule.pricer_schedule : name => schedule.arn }
}

output "setup_instructions" {
  description = "Instructions for testing the Pricer Lambda"
  value       = <<-EOT

    ✅ Pricer Lambda deployed: ${aws_lambda_function.pricer.function_name}

    ${var.enable_scheduler ? "⏰ Prices refresh every 15 minutes 09:15-15:30 IST; bars, NAVs and snapshots at 16:15 and 23:30 IST (no analysis jobs are queued)" : "💡 The Lambda is deployed but NOT scheduled. Set enable_scheduler = true and re-apply to refresh prices during NSE hours."}

    To invoke manually and check behavior before enabling the schedule:
      aws lambda invoke --function-name ${aws_lambda_function.pricer.function_name} --payload '{}' /tmp/pricer_output.json
      cat /tmp/pricer_output.json

    Monitor in CloudWatch Logs:
      aws logs tail /aws/lambda/${var.name_prefix}-pricer --follow
  EOT
}
