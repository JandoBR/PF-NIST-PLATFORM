resource "aws_db_instance" "clientes" {
  identifier              = "clientes-db"
  engine                  = "postgres"
  instance_class          = "db.t3.small"
  allocated_storage       = 50
  storage_encrypted       = true
  kms_key_id              = "alias/aws/rds"
  backup_retention_period = 14
  publicly_accessible     = false
}

resource "aws_db_instance" "reportes" {
  identifier              = "reportes-db"
  engine                  = "postgres"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  storage_encrypted       = false
  backup_retention_period = 14
  publicly_accessible     = false
}

resource "aws_s3_bucket" "documentos" {
  bucket = "org-documentos-prod"
}

resource "aws_s3_bucket" "exportes" {
  bucket = "org-exportes-prod"
}

resource "aws_cloudtrail" "main" {
  name                  = "org-trail"
  s3_bucket_name        = aws_s3_bucket.documentos.id
  is_multi_region_trail = false
  enable_logging        = true
}
