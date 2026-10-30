# Un usuario con credencial de larga duracion y una politica de contrasenas de seis caracteres,
# escrita en el propio IaC: no es silencio, es un control debil declarado.
resource "aws_iam_user" "operador" {
  name = "operador-legacy"
}

resource "aws_iam_account_password_policy" "cuenta" {
  minimum_password_length = 6
}
