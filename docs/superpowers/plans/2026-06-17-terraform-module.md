# Terraform Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a reusable Terraform module at `infra/` that provisions all GCP prerequisites for deploying agent-mesh to Vertex AI Agent Engine.

**Architecture:** The module itself contains no provider block — consumers configure the `google` provider in their own deployment repo. All nine GCP resources live in `infra/main.tf`. The `examples/complete/` directory provides a working reference that doubles as open-source documentation.

**Tech Stack:** Terraform >= 1.5, hashicorp/google provider >= 5.0, GCP (aiplatform, iam, storage, Workload Identity Federation)

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `infra/versions.tf` | Provider source + version constraints |
| Create | `infra/variables.tf` | 4 input variables |
| Create | `infra/main.tf` | All 9 GCP resources |
| Create | `infra/outputs.tf` | 3 outputs → GitHub secrets |
| Create | `infra/examples/complete/main.tf` | Consumer provider block + module call + outputs |
| Create | `infra/examples/complete/variables.tf` | 3 variables for the example |
| Create | `infra/examples/complete/terraform.tfvars.example` | Copy-paste starting point |
| Modify | `Makefile` | Add infra-init / infra-plan / infra-apply targets |
| Modify | `.gitignore` | Terraform state + local config ignores |

---

### Task 1: Module scaffold — versions.tf + variables.tf

**Files:**
- Create: `infra/versions.tf`
- Create: `infra/variables.tf`

- [ ] **Step 1: Create `infra/versions.tf`**

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}
```

Note: no `provider "google" {}` block here — consumers configure the provider in their own repo.

- [ ] **Step 2: Create `infra/variables.tf`**

```hcl
variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region for all resources"
  default     = "us-central1"
}

variable "github_repo" {
  type        = string
  description = "GitHub repository in owner/repo format — only this repo can impersonate the service account"
}

variable "bucket_name_suffix" {
  type        = string
  description = "Appended to project_id to form the staging bucket name"
  default     = "agent-mesh-staging"
}
```

- [ ] **Step 3: Init the module (downloads google provider)**

```bash
cd infra && terraform init
```

Expected output includes: `Terraform has been successfully initialized!`

- [ ] **Step 4: Validate — no resources yet but config must be valid**

```bash
cd infra && terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 5: Commit**

```bash
git add infra/versions.tf infra/variables.tf
git commit -m "feat(infra): scaffold terraform module with provider constraints and variables"
```

---

### Task 2: API enablement resources

**Files:**
- Create: `infra/main.tf` (initial content — APIs only)

- [ ] **Step 1: Create `infra/main.tf` with the three API enablement resources**

```hcl
# --- API enablement ---

resource "google_project_service" "aiplatform" {
  project            = var.project_id
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam" {
  project            = var.project_id
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "storage" {
  project            = var.project_id
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}
```

`disable_on_destroy = false` prevents Terraform from disabling APIs when the module is destroyed — other workloads in the project may depend on them.

- [ ] **Step 2: Validate**

```bash
cd infra && terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add infra/main.tf
git commit -m "feat(infra): enable aiplatform, iam, storage APIs"
```

---

### Task 3: Staging bucket + service account

**Files:**
- Modify: `infra/main.tf` (append bucket + SA blocks)

- [ ] **Step 1: Append bucket and service account resources to `infra/main.tf`**

```hcl
# --- Staging bucket ---

resource "google_storage_bucket" "staging" {
  project                     = var.project_id
  name                        = "${var.project_id}-${var.bucket_name_suffix}"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  depends_on = [google_project_service.storage]
}

# --- Service account ---

resource "google_service_account" "deploy" {
  project      = var.project_id
  account_id   = "agent-mesh-deploy"
  display_name = "agent-mesh CI/CD"

  depends_on = [google_project_service.iam]
}
```

- [ ] **Step 2: Validate**

```bash
cd infra && terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add infra/main.tf
git commit -m "feat(infra): add staging bucket and deploy service account"
```

---

### Task 4: IAM roles + Workload Identity Federation

**Files:**
- Modify: `infra/main.tf` (append IAM + WIF blocks)

- [ ] **Step 1: Append IAM role bindings to `infra/main.tf`**

```hcl
# --- IAM roles ---

resource "google_project_iam_member" "aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_project_iam_member" "storage_object_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}
```

- [ ] **Step 2: Append WIF pool, provider, and SA binding to `infra/main.tf`**

```hcl
# --- Workload Identity Federation ---

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "agent-mesh-github"
  display_name              = "agent-mesh GitHub Actions"

  depends_on = [google_project_service.iam]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions OIDC"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  attribute_condition = "assertion.repository == '${var.github_repo}'"
}

resource "google_service_account_iam_member" "wif_binding" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
```

- [ ] **Step 3: Validate**

```bash
cd infra && terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add infra/main.tf
git commit -m "feat(infra): add IAM roles and Workload Identity Federation for GitHub Actions"
```

---

### Task 5: Outputs

**Files:**
- Create: `infra/outputs.tf`

- [ ] **Step 1: Create `infra/outputs.tf`**

```hcl
output "wif_provider" {
  description = "Workload Identity Federation provider — set as WIF_PROVIDER GitHub secret"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "service_account_email" {
  description = "Service account email — set as WIF_SERVICE_ACCOUNT GitHub secret"
  value       = google_service_account.deploy.email
}

output "staging_bucket" {
  description = "GCS staging bucket URI — set as GOOGLE_CLOUD_STAGING_BUCKET GitHub secret"
  value       = "gs://${google_storage_bucket.staging.name}"
}
```

- [ ] **Step 2: Validate**

```bash
cd infra && terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add infra/outputs.tf
git commit -m "feat(infra): add outputs mapping to GitHub secrets"
```

---

### Task 6: Consumer example

**Files:**
- Create: `infra/examples/complete/main.tf`
- Create: `infra/examples/complete/variables.tf`
- Create: `infra/examples/complete/terraform.tfvars.example`

- [ ] **Step 1: Create `infra/examples/complete/variables.tf`**

```hcl
variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
  default     = "us-central1"
}

variable "github_repo" {
  type        = string
  description = "GitHub repository in owner/repo format (e.g. acme/my-deployment)"
}
```

- [ ] **Step 2: Create `infra/examples/complete/main.tf`**

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "agent_mesh_infra" {
  # When consuming from a release tag use:
  # source = "github.com/your-org/agent-mesh//infra?ref=v0.1.0"
  source = "../../"

  project_id  = var.project_id
  region      = var.region
  github_repo = var.github_repo
}

output "github_secrets" {
  description = "Set these as GitHub secrets in your deployment repo"
  value = {
    WIF_PROVIDER                = module.agent_mesh_infra.wif_provider
    WIF_SERVICE_ACCOUNT         = module.agent_mesh_infra.service_account_email
    GOOGLE_CLOUD_STAGING_BUCKET = module.agent_mesh_infra.staging_bucket
  }
}
```

- [ ] **Step 3: Create `infra/examples/complete/terraform.tfvars.example`**

```hcl
project_id  = "my-gcp-project"
region      = "us-central1"
github_repo = "your-org/your-deployment-repo"
```

- [ ] **Step 4: Init and validate the example**

```bash
cd infra/examples/complete && terraform init && terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 5: Commit**

```bash
git add infra/examples/
git commit -m "feat(infra): add complete consumer example"
```

---

### Task 7: Makefile + .gitignore

**Files:**
- Modify: `Makefile`
- Modify: `.gitignore`

- [ ] **Step 1: Add infra targets to `Makefile`**

Change the `.PHONY` line at the top of `Makefile` to:

```makefile
.PHONY: run test lint install jaeger deploy infra-init infra-plan infra-apply
```

Then append after the existing `jaeger` target:

```makefile
infra-init:
	cd infra && terraform init

infra-plan:
	cd infra && terraform plan -var-file=terraform.tfvars

infra-apply:
	cd infra && terraform apply -var-file=terraform.tfvars
```

- [ ] **Step 2: Append Terraform ignores to `.gitignore`**

```
infra/*.tfvars
infra/.terraform/
infra/*.tfstate
infra/*.tfstate.backup
infra/examples/**/*.tfvars
infra/examples/**/.terraform/
infra/examples/**/*.tfstate
infra/examples/**/*.tfstate.backup
```

- [ ] **Step 3: Validate Makefile targets parse correctly**

```bash
make --dry-run infra-init
```

Expected: prints `cd infra && terraform init` without error.

- [ ] **Step 4: Final commit**

```bash
git add Makefile .gitignore
git commit -m "feat(infra): add make targets and gitignore rules for terraform"
```
