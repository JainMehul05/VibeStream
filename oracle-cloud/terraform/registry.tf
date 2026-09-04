Select-String -Path "oracle-cloud/scripts/push-images.sh" -Pattern "kubectl set image"resource "oci_artifacts_container_repository" "frontend" {
  compartment_id = var.compartment_ocid
  display_name   = "vibestream-frontend"
  is_public      = false
  freeform_tags  = local.common_tags
}

resource "oci_artifacts_container_repository" "backend" {
  compartment_id = var.compartment_ocid
  display_name   = "vibestream-backend"
  is_public      = false
  freeform_tags  = local.common_tags
}

resource "oci_artifacts_container_repository" "ai_ml" {
  compartment_id = var.compartment_ocid
  display_name   = "moodify-ai-ml"
  is_public      = false
  freeform_tags  = local.common_tags
}
