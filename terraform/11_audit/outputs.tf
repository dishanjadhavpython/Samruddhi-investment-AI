output "audit_bucket" {
  description = "Audit log bucket; terraform/6_agents passes it to every agent as AUDIT_BUCKET"
  value       = aws_s3_bucket.audit.id
}

output "setup_instructions" {
  value = <<-EOT

    ✅ Audit log bucket: ${aws_s3_bucket.audit.id}
       Object Lock ${var.lock_mode}, ${var.retention_days} days per record.

    Agents find it by name (${var.name_prefix}-audit-<account id>). List one job's records:
      aws s3 ls s3://${aws_s3_bucket.audit.id}/v1/jobs/<job id>/ --recursive

    Replay a report from its records:
      cd backend/evals && uv run replay.py <job id>
  EOT
}
