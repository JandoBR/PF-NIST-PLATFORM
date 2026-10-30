# Identidades declaradas en IaC y autenticacion endurecida al umbral del CIS AWS Foundations
# Benchmark (14 caracteres), con una politica que niega todo si no hay MFA presente.
resource "aws_iam_role" "aplicacion" {
  name = "aplicacion-produccion"

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
  minimum_password_length        = 14
  require_symbols                = true
  require_numbers                = true
  require_uppercase_characters   = true
  max_password_age               = 90
  password_reuse_prevention      = 24
  allow_users_to_change_password = true
}

resource "aws_iam_policy" "exigir_mfa" {
  name        = "exigir-mfa"
  description = "Niega toda accion salvo gestionar la propia credencial si no hay MFA presente."

  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenegarSinMFA",
    "Effect": "Deny",
    "NotAction": [
      "iam:ChangePassword",
      "iam:CreateVirtualMFADevice",
      "iam:EnableMFADevice",
      "sts:GetSessionToken"
    ],
    "Resource": "*",
    "Condition": {
      "BoolIfExists": { "aws:MultiFactorAuthPresent": "false" }
    }
  }]
}
EOF
}

# Capacidad elastica: el grupo puede crecer de 2 a 6 instancias con la carga.
resource "aws_autoscaling_group" "aplicacion" {
  name             = "aplicacion-produccion"
  min_size         = 2
  max_size         = 6
  desired_capacity = 2
}
