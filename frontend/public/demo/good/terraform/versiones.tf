# Procedencia del codigo de terceros (convencion `versions.tf`): el proveedor y los modulos del
# registry estan fijados, asi que dos `terraform init` traen lo mismo.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

module "red" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.8.1"

  name = "red-principal"
  cidr = "10.0.0.0/16"
}

# Modulo propio del repositorio: no se adquiere a nadie, no hay version que fijar.
module "etiquetas" {
  source = "./modulos/etiquetas"

  entorno = "produccion"
}
