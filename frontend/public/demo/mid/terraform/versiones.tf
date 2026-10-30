# El modulo del registry esta fijado, pero el proveedor se declara sin restriccion de version:
# un `terraform init` de la semana que viene puede traer otro AWS provider.
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

module "red" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.8.1"

  name = "red-clientes"
  cidr = "10.1.0.0/16"
}
