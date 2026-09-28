output "market_function_name" {
  description = "Name of the market_eod Lambda function"
  value       = aws_lambda_function.market_eod.function_name
}

output "market_bucket" {
  description = "Bucket for manual NSE Indices downloads (incoming/) and the Lambda package"
  value       = aws_s3_bucket.market.id
}

output "scheduler_status" {
  description = "Status of the daily market run"
  value       = var.enable_scheduler ? "Enabled - 19:00 IST, Mon-Fri" : "Disabled - set enable_scheduler = true to activate"
}

output "setup_instructions" {
  description = "How to run and feed the market pipeline"
  value       = <<-EOT

    ✅ Market Lambda deployed: ${aws_lambda_function.market_eod.function_name}

    Run it now:
      aws lambda invoke --function-name ${aws_lambda_function.market_eod.function_name} --payload '{}' --cli-binary-format raw-in-base64-out market_output.json

    Add valuation or TRI files downloaded from niftyindices.com (picked up by the next run):
      aws s3 cp nifty50_pe_pb.csv s3://${aws_s3_bucket.market.id}/incoming/

    Or load them straight from your machine:
      cd backend/market && uv run ingest.py nse_data/

    Logs:
      aws logs tail /aws/lambda/${aws_lambda_function.market_eod.function_name} --follow
  EOT
}

output "market_latest_table" {
  description = "DynamoDB table the pricer writes and /api/market/snapshot reads"
  value       = aws_dynamodb_table.market_latest.name
}

output "market_intraday_table" {
  description = "DynamoDB table of 5-minute points (7-day TTL)"
  value       = aws_dynamodb_table.market_intraday.name
}
