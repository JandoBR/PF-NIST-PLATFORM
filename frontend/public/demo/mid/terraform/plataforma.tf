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

# El grupo si puede crecer, pero ninguna base declara multi_az ni es replica: se aguanta la carga,
# no se sobrevive a una zona caida.
resource "aws_autoscaling_group" "aplicacion" {
  name             = "aplicacion-clientes"
  min_size         = 2
  max_size         = 4
  desired_capacity = 2
}

# El balanceador sigue escuchando en claro: el dato en reposo ya se arreglo a medias, el de viaje
# no se ha tocado.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.aplicacion.arn
  port              = 80
  protocol          = "HTTP"
}
