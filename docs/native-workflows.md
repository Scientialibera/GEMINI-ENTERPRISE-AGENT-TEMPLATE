# Native workflow registration

Optional [access-group setup](agent-access-groups.md) grants the same group use
permission on both the native wrapper and its ADK backend. Existing workflow
graphs and schedules are preserved. Disabled wrappers require a state review;
if a wrapper remains private after sharing, publish it before retrying verification.

Entries with `source_root="workflows"` deploy their Python pipeline to Agent Engine.
Registration then creates two Gemini Enterprise resources:

- **Recipe Card Workflow Backend** is the ADK registration required by the reference node.
- **Recipe Card Workflow** is the native workflow users should open.

Both remain available. Disabling or deleting the backend can break the wrapper;
there is no verified hidden-but-callable setting. A native wrapper references an
app agent resource, not a Reasoning Engine directly.

## Release a workflow

```bash
uv run --group dev python dev/release_dev.py --agent recipe_card_workflow
```

To register an already-deployed runtime without deploying again:

```bash
uv run --group dev python dev/register/register_agent.py --agent recipe_card_workflow
```

`--skip-register` on the release helper skips both registrations. Regular agent
entries continue to create only their ADK registration.

## First release and migration

The helper creates an enabled wrapper with a manual trigger and one
`AGENT_REFERENCE_NODE` referencing the backend. It does not create a schedule.
The default prompt asks the backend to collect missing inputs and complete its
pipeline. Configure explicit input mappings in Workflow Builder if needed;
the helper does not invent trigger-variable expressions.

An existing ADK registration for the same runtime is reused and renamed with the
`Backend` suffix, preserving its resource ID and existing references. Multiple
registrations for that runtime, conflicting backend names or an unmanaged native
workflow under the intended name stop registration rather than overwrite data.
The earlier **Recipe Card Workflow API Test** remains separate and is not adopted
or deleted automatically.

## Later releases

The helper identifies its wrapper by the description marker
`Managed native workflow wrapper: <package_name>`. Keep this marker intact.
It preserves the existing graph, prompt, schedule and sharing state. If that
graph no longer references the expected backend, registration fails for manual
review. The wrapper is read back to verify its reference. Creation failure leaves
the backend registered; a retry reuses it.

Serialize releases per workflow and app. This integration has no verified API
idempotency key, so do not register the same workflow concurrently. Inspect
resources after an interrupted or ambiguous API response before retrying.

## Test in the app

Enable Workflow Builder and ensure intended users can access both resources.
Open **Recipe Card Workflow**, enter a recipe request and confirm the backend
returns a real deck link. Open that deck as the intended user and check its
content. Test missing-input handling, recovery and access as another user before
sharing widely. Recipe generation incurs API charges.

The wrapper calls the Python workflow as one step. The writer, image director
and renderer remain Python stages, not separate native canvas nodes. Runtime
prompts and models remain controlled by Parameter Manager; the native node's
handoff prompt is separate and maintained in Workflow Builder.

## API support status

On 22 September 2026, a UI-created example revealed the native reference payload.
Creating and retrieving a private manual wrapper through the authenticated
Discovery Engine v1alpha API succeeded; the user also confirmed it in the app.
The integrated helper subsequently renamed the existing recipe backend, created
an enabled native wrapper and reused both resource IDs on a second registration.
These checks did not run recipe generation.
The public discovery schema still omits `workflowAgentDefinition`. This is an
observed, undocumented integration, not a published Google API contract. API
round-trip verification does not replace testing the workflow's execution.

Implementation: `dev/register/native_workflow.py`. Native registration uses
`workflowAgentDefinition.agentFlow` with `MANUAL_TRIGGER` and
`AGENT_REFERENCE_NODE`, whose `agentReferenceType` is `ADK_AGENT`.

Sources: [Existing agent steps](https://docs.cloud.google.com/gemini/enterprise/docs/workflow-builder/add-existing-agents)
and [agent states](https://docs.cloud.google.com/gemini/enterprise/docs/agents-overview).
