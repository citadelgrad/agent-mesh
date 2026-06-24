# IAM Setup

## Agent Engine (Phase 3)

The runtime service account needs permission to invoke Agent Engine reasoning engines:

```bash
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

## Agent Registry (Phase 4)

Read-only access for `AgentRegistryCatalog` to discover agents. Managed in Terraform via
`google_project_iam_member.agentregistry_viewer` in `agent-mesh-deploy/infra/main.tf`.

Enable after deploying Phase 4 by setting `AGENT_MESH_USE_REGISTRY=1` in `.envrc`.

> **Quota note:** Agent Registry is limited to 100 agents/region in the v1alpha API.
