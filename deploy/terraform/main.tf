terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    # Bucket is configured at init time via -backend-config flag.
    # See setup.sh and cloudbuild.yaml for details.
    prefix = "healthcare-mcp"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Artifact Registry – single repo for all server images
# ---------------------------------------------------------------------------

resource "google_artifact_registry_repository" "mcp_repo" {
  location      = var.region
  repository_id = var.repo_name
  format        = "DOCKER"
  description   = "Docker images for Healthcare MCP servers"
}

# ---------------------------------------------------------------------------
# Cloud Run services – Core MCP Servers
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "mcp_server" {
  for_each = var.servers

  name     = each.key
  location = var.region

  template {
    scaling {
      min_instance_count = each.value.min_instances
      max_instance_count = each.value.max_instances
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repo_name}/${each.value.image_name}:${var.image_tag}"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          memory = each.value.memory
          cpu    = each.value.cpu
        }
      }

      dynamic "env" {
        for_each = each.value.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }
}

# ---------------------------------------------------------------------------
# IAM – configurable via auth_mode
# ---------------------------------------------------------------------------

data "google_iam_policy" "public_invoker" {
  binding {
    role    = "roles/run.invoker"
    members = ["allUsers"]
  }
}

# --- auth_mode = "public": all services open to anyone ---

resource "google_cloud_run_v2_service_iam_policy" "public_policy" {
  for_each = { for k, v in var.servers : k => v if v.auth_mode == "public" }

  name        = google_cloud_run_v2_service.mcp_server[each.key].name
  location    = var.region
  policy_data = data.google_iam_policy.public_invoker.policy_data
}

# --- auth_mode = "iam": services restricted ---

resource "google_service_account" "gemini_enterprise" {
  count        = length([for k, v in var.servers : v if v.auth_mode == "iam"]) > 0 ? 1 : 0
  account_id   = "gemini-mcp-sa"
  display_name = "Gemini Enterprise MCP Service Account"
  description  = "Used by Gemini Enterprise to securely invoke IAM-protected MCP servers."
}

data "google_iam_policy" "private_invoker" {
  count = length([for k, v in var.servers : v if v.auth_mode == "iam"]) > 0 ? 1 : 0
  binding {
    role = "roles/run.invoker"
    members = concat(
      ["serviceAccount:${google_service_account.gemini_enterprise[0].email}"],
      [for email in var.developer_emails : "user:${email}"]
    )
  }
}

resource "google_cloud_run_v2_service_iam_policy" "private_policy" {
  for_each = { for k, v in var.servers : k => v if v.auth_mode == "iam" }

  name        = google_cloud_run_v2_service.mcp_server[each.key].name
  location    = var.region
  policy_data = data.google_iam_policy.private_invoker[0].policy_data
}

data "google_project" "project" {}

resource "google_project_iam_binding" "iap_accessor" {
  count   = length([for k, v in var.servers : v if v.auth_mode == "iam"]) > 0 ? 1 : 0
  project = var.project_id
  role    = "roles/iap.httpsResourceAccessor"

  members = concat(
    ["serviceAccount:${google_service_account.gemini_enterprise[0].email}"],
    [for email in var.developer_emails : "user:${email}"]
  )
}