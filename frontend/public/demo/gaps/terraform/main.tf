resource "aws_db_instance" "legacy" {
  identifier              = "legacy-db"
  engine                  = "mysql"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  storage_encrypted       = false
  backup_retention_period = 0
  publicly_accessible     = true
}

resource "aws_db_instance" "reportes" {
  identifier              = "reportes-db"
  engine                  = "postgres"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  storage_encrypted       = true
  backup_retention_period = 3
  publicly_accessible     = false
}

resource "aws_s3_bucket" "backups" {
  bucket = "org-backups-prod"
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = false
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_security_group" "legacy_app" {
  name = "legacy-app-sg"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
