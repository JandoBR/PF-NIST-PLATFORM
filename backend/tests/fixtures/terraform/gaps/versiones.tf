# Dos modulos traidos de git sin `?ref=`: lo que se despliegue manana no es necesariamente lo que
# se reviso hoy. Y no hay `required_providers` en ninguna parte.
module "legacy_red" {
  source = "github.com/acme-interno/terraform-red"

  nombre = "red-legacy"
}

module "reportes" {
  source = "git::https://git.acme-interno.local/infra/reportes.git"
}
