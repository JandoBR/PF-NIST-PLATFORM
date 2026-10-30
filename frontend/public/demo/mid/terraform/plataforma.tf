# El rol de la aplicacion ya esta en IaC, pero la politica de contrasenas se quedo en 10
# caracteres: por debajo de los 14 del CIS AWS, y no hay ninguna politica que exija MFA.
resource "aws_iam_role" "aplicacion" {
  name = "aplicacion-clientes"

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ec2.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF
}

resource "aws_iam_account_password_policy" "cuenta" {
  minimum_password_length   = 10
  require_numbers           = true
  password_reuse_prevention = 3
}
