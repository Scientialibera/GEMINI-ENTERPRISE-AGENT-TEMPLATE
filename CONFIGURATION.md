# Configuration ownership and change workflow

## Classes

| Value | Authoritative location | Runtime location |
|---|---|---|
| Project, Agent Engine, scaling, IAM, logging | Terraform | Google Cloud resources |
| Live non-secret agent behavior | Terraform `runtime_config` | Parameter Manager |
| Process-construction values | Terraform `bootstrap_env` | Agent Engine environment |
| Secret payloads | Approved secret source | Secret Manager |
| Developer-local overrides | Agent repo ignored `.env` files | Developer workstation/sandbox |

Do not keep the same shared live setting in Terraform, Agent Engine env and a deployed `.env` file.

## Initial variables

`variables.tf` defines the contract. Copy `terraform.tfvars.example` to the target environment root and replace the applicable placeholders. Supply `TF_VAR_config_revision` separately.

Secret payloads are never placed in `terraform.tfvars`.

## Runtime publish flow

```text
Git change
  -> PR/review
  -> terraform plan
  -> terraform apply
  -> immutable Parameter Manager version
  -> /versions/latest
  -> running agent refreshes after TTL
```

Terraform injects `config_revision` into the JSON payload and includes both the revision and a content hash in the Parameter Manager version ID.

Changing only live runtime configuration does not rebuild or redeploy agent source.

## Development UI changes

Direct Parameter Manager versions may be permitted in developer/shared-dev environments for testing. They are out-of-band relative to Git.

If the experiment is retained:

1. copy the accepted value into Terraform `runtime_config`;
2. review/merge the change;
3. apply Terraform;
4. allow Terraform to publish the canonical new Parameter Manager version.

QA and production should normally restrict Parameter Manager writes to the Terraform execution identity.

## Drift policy

- Developers and Agent Identities normally receive Parameter Manager read access only.
- Terraform execution identity owns shared parameter/version creation.
- Manual shared-environment changes are treated as drift.
- Break-glass changes must be reconciled into Git immediately.
- Rollback is a new approved configuration publish, not a permanent manual pointer to an unmanaged old version.

## Bootstrap changes

Values required to construct the process, SDK client or authenticated ADK tool graph belong in `bootstrap_env`. Changing them updates the Agent Engine deployment specification and can create a new Agent Runtime revision.

Normal operational tunables should remain in Parameter Manager.
