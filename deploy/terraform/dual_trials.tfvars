servers = {
  # --- Private (IAM) Servers ---
  "rxnorm-mcp"         = { image_name = "rxnorm-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "clinical-trials-mcp" = { image_name = "clinical-trials-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "drug-data-mcp"      = { image_name = "drug-data-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "umls-mcp"           = { image_name = "umls-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "pubmed-mcp"         = { image_name = "pubmed-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "fda-safety-mcp"     = { image_name = "fda-safety-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "icd10-mcp"          = { image_name = "icd10-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "cms-coverage-mcp"   = { image_name = "cms-coverage-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "medlineplus-mcp"    = { image_name = "medlineplus-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "npi-mcp"            = { image_name = "npi-mcp", auth_mode = "iam", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }

  # --- Public Servers ---
  "rxnorm-mcp-public"         = { image_name = "rxnorm-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "clinical-trials-mcp-public" = { image_name = "clinical-trials-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "drug-data-mcp-public"      = { image_name = "drug-data-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "umls-mcp-public"           = { image_name = "umls-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "pubmed-mcp-public"         = { image_name = "pubmed-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "fda-safety-mcp-public"     = { image_name = "fda-safety-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "icd10-mcp-public"          = { image_name = "icd10-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "cms-coverage-mcp-public"   = { image_name = "cms-coverage-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "medlineplus-mcp-public"    = { image_name = "medlineplus-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
  "npi-mcp-public"            = { image_name = "npi-mcp", auth_mode = "public", env_vars = {}, min_instances = 0, max_instances = 1, memory = "512Mi", cpu = "1" }
}
