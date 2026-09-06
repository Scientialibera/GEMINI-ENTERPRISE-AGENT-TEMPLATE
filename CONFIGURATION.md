# Configuration ownership and change workflow

## Classes

| Value | Authoritative location | Runtime location |
|---|---|---|
| Project, IAM, secrets, logging | Terraform | Google Cloud resources |
| Live non-secret agent behavior | Agent repository | Parameter Manager |
| Process-construction values | Agent repository bootstrap env | Agent Engine environment |
| Secret payloads | Approved secret source | Secret Manager |
| Developer-local overrides | Agent repo ignored `.env` files | Developer workstation/sandbox |

Only the first and fourth rows belong to this stack. Agent behavior and deployment moved to the agent repository so that adding an agent is not an infrastructure change.

Do not keep the same shared live setting in Terraform, Agent Engine env and a deployed `.env` file.

## Initial variables

`variables.tf` defines the contract. Copy `terraform.tfvars.example` to the target environment root and replace the applicable placeholders.

Secret payloads are never placed in `terraform.tfvars`.

## Runtime publish flow

Runtime configuration is owned by the agent repository. Each agent reads its own Parameter Manager parameter, named after its package, and refreshes after a cache interval:

```text
Agent repository change
  -> PR/review
  -> publish parameter version
  -> /versions/latest
  -> running agent refreshes after TTL
```

Publishing configuration does not rebuild or redeploy agent source, and does not require a Terraform apply.

## Development UI changes

Direct Parameter Manager versions may be permitted in developer/shared-dev environments for testing. They are out-of-band relative to Git.

If the experiment is retained, copy the accepted value back into the agent repository so the published version is reproducible from source.

QA and production should normally restrict Parameter Manager writes to the release identity.

## Drift policy

- Agent Identities normally receive Parameter Manager read access only, granted here through the all-agent principal set.
- The agent repository's release path owns parameter/version creation.
- Manual shared-environment changes are treated as drift.
- Break-glass changes must be reconciled into Git immediately.
- Rollback is a new approved configuration publish, not a permanent manual pointer to an unmanaged old version.

## Bootstrap changes

Values required to construct the process, SDK client or authenticated ADK tool graph are bootstrap configuration, set by the agent repository at deploy time. Changing them updates the Agent Engine deployment specification and can create a new Agent Runtime revision.

Normal operational tunables should remain in Parameter Manager.
