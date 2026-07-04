provider "aws" {
  # VIOLATION: Hardcoded region (Rule: tf-no-hardcoded-region)
  region = "us-east-1"
}

resource "aws_s3_bucket" "data_bucket" {
  bucket = "payment-data-bucket-prod"
  acl    = "private"
}
