# Terraform Module Design — agent-mesh GCP Infrastructure

**Date:** 2026-06-17
**Status:** Approved

## Summary

agent-mesh ships a reusable Terraform module at `infra/` that provisions all GCP prerequisites for deploying to Vertex AI Agent Engine. The module is consumed by a separate deployment repo — agent-mesh itself is a library, not a deployment target. Agent Engine lifecycle (create/update) stays in `deploy.py`, driven by CI on every push to main. Terraform owns static infra only.

## Module Structure

```
infra/
  versions.tf                    # provider + version constraints
  variables.tf                   # project_id, region, github_repo, bucket_name_suffix
  main.tf                        # all resources
  outputs.tf                     # wif_provider, service_account_email, staging_bucket
  examples/
    complete/
      main.tf                    # full consumer wiring
      terraform.tfvars.example   # copy → terraform.tfvars, fill in values
```

Consumer references the module via git source:

```hcl
module "agent_mesh_infra" {
  source = "github.com/your-org/agent-mesh//infra?ref=v0.1.0"

  project_id  = "my-gcp-project"
  region      = "us-central1"
  github_repo = "your-org/your-deployment-repo"
}
```

## Resources Created

| Resource | Details |
|----------|---------|
| API enablement | `aiplatform.googleapis.com`, `iam.googleapis.com`, `storage.googleapis.com` |
| GCS staging bucket | `${project_id}-agent-mesh-staging` (or custom suffix), uniform bucket-level access, force_destroy = false |
| Service account | `agent-mesh-deploy@${project_id}.iam.gserviceaccount.com` |
| IAM roles on SA | `roles/aiplatform.user`, `roles/storage.objectAdmin` |
| WIF pool | OIDC pool for GitHub Actions (`agent-mesh-github`) |
| WIF provider | Bound to `https://token.actions.githubusercontent.com`, attribute condition locks to `var.github_repo` |
| WIF → SA binding | `roles/iam.workloadIdentityUser` scoped to the repo's principal set |

## Variables

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `project_id` | yes | — | GCP project ID |
| `region` | no | `us-central1` | GCP region for all resources |
| `github_repo` | yes | — | `owner/repo` — only this repo can impersonate the SA |
| `bucket_name_suffix` | no | `agent-mesh-staging` | Appended to project_id for bucket name |

## Outputs

| Output | Maps to GitHub Secret |
|--------|----------------------|
| `wif_provider` | `WIF_PROVIDER` |
| `service_account_email` | `WIF_SERVICE_ACCOUNT` |
| `staging_bucket` | `GOOGLE_CLOUD_STAGING_BUCKET` |

`GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` are set directly by the consumer from their own vars — not routed through the module.

## Consumer End-to-End Flow

1. Consumer creates a deployment repo, references this module
2. Fills in `terraform.tfvars` (project_id, region, github_repo)
3. Runs `terraform apply` — all GCP infra created, three secret values printed
4. Sets `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `GOOGLE_CLOUD_STAGING_BUCKET`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GEMINI_API_KEY` as GitHub secrets
5. Pushes to main — GHA workflow fires, `deploy.py` creates Agent Engine, prints resource name
6. Consumer adds `AGENT_ENGINE_ID` as a final GitHub secret for future updates

## Makefile Targets (for module authors)

```makefile
infra-init:   cd infra && terraform init
infra-plan:   cd infra && terraform plan -var-file=terraform.tfvars
infra-apply:  cd infra && terraform apply -var-file=terraform.tfvars
```

## .gitignore Additions

```
infra/*.tfvars
infra/.terraform/
infra/*.tfstate
infra/*.tfstate.backup
```

## Separation of Concerns

- **Terraform** owns: APIs, bucket, service account, IAM, WIF — static infra that changes rarely
- **deploy.py + GHA** owns: Agent Engine resource — dynamic, updated on every push to main
- No overlap; no Terraform resource managing the Agent Engine
