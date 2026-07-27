# Terraform for Idea Scout's frontend hosting (ADR-0018 §2).
#
# `biffo plugin install idea-scout` copies this directory into the instance's
# monorepo at modules/plugins/idea-scout/ and generates the instantiating module
# block into infra/environments/<env>/plugins.generated.tf (CLI-owned).
#
# This provisions ONLY the plugin's static frontend origin. It deliberately does
# NOT provision a Lambda or an API Gateway ingress, which is what the plugin
# skeleton's terraform/ shipped: that is ADR-0018 §1's per-plugin backend, made
# obsolete by ADR-0021's shared plugin host. Idea Scout was born on the shared
# host and never had a backend of its own — its ASGI apps are mounted by the
# host at /api/v1/plugins/idea-scout, and installing the skeleton's module
# unchanged would have created a Lambda that nothing ever invokes.
#
# ADR-0018 §2's per-plugin *frontend* hosting (a static app under its own S3
# origin, routed at <base>/idea-scout/* via the shared CloudFront's
# sibling_origins) remains current until ADR-0021's shared app-shell lands
# (biffo-template#558, not started) — so this bucket stays.
#
# Modelled on modules/plugins/ideation/ in biffo-platform, which is the same
# shape for the same reasons.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# The frontend's own S3 origin (ADR-0007 sibling shape). The built web/dist is
# deployed here; the shared CloudFront reads it (routed at <base>/idea-scout/* via
# cdn's sibling_origins, registered by install). Access is ONLY through the
# distribution — the bucket itself is fully private.
resource "aws_s3_bucket" "frontend" {
  #checkov:skip=CKV_AWS_18:Static public-app assets served via CloudFront; access logging is the distribution's, not per-bucket.
  #checkov:skip=CKV_AWS_144:Non-critical, rebuildable static assets; cross-region replication unwarranted.
  #checkov:skip=CKV2_AWS_61:Rebuildable static assets; lifecycle expiration not required.
  #checkov:skip=CKV2_AWS_62:Static assets; event notifications not applicable.
  bucket        = "${local.name_prefix}-plugin-${var.plugin_name}-web"
  force_destroy = true
  tags          = var.tags
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Read access for the shared CloudFront distribution only (its OAC signs the
# request; the condition ties the grant to this exact distribution).
data "aws_iam_policy_document" "frontend" {
  statement {
    sid       = "AllowSharedCloudFrontRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [var.cdn_distribution_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend.json
}
