resource "aws_db_instance" "principal" {
  identifier              = "principal-db"
  engine                  = "postgres"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  storage_encrypted       = true
  kms_key_id              = "alias/aws/rds"
  backup_retention_period = 14
  publicly_accessible     = false
  multi_az                = true
}

resource "aws_s3_bucket" "documentos" {
  bucket = "org-documentos-prod"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documentos" {
  bucket = aws_s3_bucket.documentos.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = "alias/aws/s3"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documentos" {
  bucket                  = aws_s3_bucket.documentos.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "documentos" {
  bucket = aws_s3_bucket.documentos.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_security_group" "app" {
  name        = "app-sg"
  description = "Security group for app servers"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_cloudtrail" "main" {
  name                  = "org-trail"
  s3_bucket_name        = aws_s3_bucket.documentos.id
  is_multi_region_trail = true
  enable_logging        = true
}
