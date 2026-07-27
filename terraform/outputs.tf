# This module now provisions ONLY the frontend's S3 origin (ADR-0021 phase C —
# the backend Lambda/API-Gateway ingress it used to provision was torn down;
# ADR-0018 §2's per-plugin frontend hosting remains current until ADR-0021's
# shared app-shell lands, biffo-template#558). frontend_bucket_regional_domain
# -> cdn's sibling_origins (the <idea-scout>/* frontend behaviour).
# frontend_bucket_name is the deploy target the built web/dist is synced to.

output "frontend_bucket_regional_domain" {
  description = "The frontend bucket's regional domain — the sibling_origins origin."
  value       = aws_s3_bucket.frontend.bucket_regional_domain_name
}

output "frontend_bucket_name" {
  description = "The frontend bucket name — the deploy target for the built web/dist."
  value       = aws_s3_bucket.frontend.id
}
