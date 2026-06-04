variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run services"
  type        = string
  default     = "us-central1"
}

variable "repo_name" {
  description = "Artifact Registry repository name"
  type        = string
  default     = "healthcare-mcp"
}

variable "image_tag" {
  description = "Docker image tag to deploy (e.g., 'latest' or a git SHA)"
  type        = string
  default     = "latest"
}

variable "auth_mode" {
  description = "Authentication mode for Cloud Run services: 'iam' (default, requires Cloud IAM invoker role) or 'public' (no auth, services accessible to anyone with the URL)"
  type        = string
  default     = "iam"

  validation {
    condition     = contains(["iam", "public"], var.auth_mode)
    error_message = "auth_mode must be 'iam' or 'public'."
  }
}

variable "developer_emails" {
  description = "List of developer emails to grant IAP/Cloud Run Invoker access (only used when auth_mode=iam)"
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------
# Server definitions – add new servers here as they are built.
# Each key is the Cloud Run service name.
# ---------------------------------------------------------------------------

variable "servers" {
  description = "Map of MCP servers to deploy. Key = Cloud Run service name."
  type = map(object({
    image_name    = string               # Image name in Artifact Registry
    auth_mode     = optional(string, "iam") # "iam" or "public" (defaults to "iam")
    env_vars      = map(string)          # Environment variables (optional)
    min_instances = number       # Minimum instances (0 = scale to zero)
    max_instances = number       # Maximum instances
    memory        = string       # Memory allocation (e.g., "512Mi", "1Gi")
    cpu           = string       # CPU allocation (e.g., "1", "2")
  }))

  default = {
    "rxnorm-mcp" = {
      image_name    = "rxnorm-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "clinical-trials-mcp" = {
      image_name    = "clinical-trials-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "drug-data-mcp" = {
      image_name    = "drug-data-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "umls-mcp" = {
      image_name    = "umls-mcp"
      env_vars      = {}  # API key passed via URL query param, not env var
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "pubmed-mcp" = {
      image_name    = "pubmed-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "fda-safety-mcp" = {
      image_name    = "fda-safety-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "icd10-mcp" = {
      image_name    = "icd10-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "cms-coverage-mcp" = {
      image_name    = "cms-coverage-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "medlineplus-mcp" = {
      image_name    = "medlineplus-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
    "npi-mcp" = {
      image_name    = "npi-mcp"
      env_vars      = {}
      min_instances = 0
      max_instances = 1
      memory        = "512Mi"
      cpu           = "1"
    }
  }
}
