# Create a native recipe workflow

`recipe_card_workflow` is a Python ADK SequentialAgent. Its stages run on Agent
Engine and its listing uses `adkAgentDefinition`. It does not create a native
Workflow Builder workflow or its workflow badge.

Google supports adding a registered ADK agent as an **Existing agent** step in a
native workflow. Keep the backend and create a separate wrapper to retain Python
image generation, shared pacing and PowerPoint rendering.

## Deploy the backend

Complete the root README's project, bucket, identity and app setup, then run:

```bash
uv run --group dev python dev/release_dev.py --agent recipe_card_workflow
```

Confirm **Recipe Card Workflow** is published and available to your user in the
same project. Test it directly before adding the wrapper. Generation incurs API
charges; reuse existing photography where possible.

## Create the native workflow

1. Have an administrator enable Workflow Builder if it is unavailable.
2. In the Gemini Enterprise web app, create a workflow named **Recipe Card Workflow
   (Native)**. Keep its name distinct from the ADK backend's **Recipe Card Workflow**.
3. Start with a manual trigger. Configure the recipe request, including servings
   and ingredient substitutions, as input.
4. Choose **Add step → Existing agents → Recipe Card Workflow**. A plain Gemini
   Agent step does not carry this repository's Python tools.
5. Insert the recipe input into the step's Prompt using the builder's variable
   picker. Add this instruction:

   > Create the requested recipe card using your complete recipe pipeline. Preserve
   > the requested servings and substitutions. Return the published deck link only
   > after rendering succeeds. If generation is incomplete, explain what remains
   > and retain the run identifier so the photographs can be reused.

   Pass inputs explicitly; other workflow variables are not automatically available
   to the referenced agent. Do not type a guessed variable expression.
6. Preview the workflow. Confirm the Existing agent step returns a real deck link,
   then open the deck as the intended user and check ingredients, customizations
   and images. A successful wrapper run alone does not validate the card content.
7. Make the workflow live and verify its workflow presentation in the app. Sharing
   the wrapper does not replace backend availability or Cloud Storage permissions.

The picker shows published ADK/A2A agents shared with the current user in the same
project. If an agent is missing, check publication, project and sharing. Delegated
agents require authentication before starting a new workflow run. The recipe
backend uses Agent Identity for storage operations.

## What the comparison demonstrates

`recipe_card_agent` chooses tools conversationally. `recipe_card_workflow` fixes
writer → image director → renderer in Python. The native wrapper calls the latter
as **one Existing agent step**; the three Python stages are not separate canvas
nodes. Making the canvas own each stage would require separately deployed stage
agents and explicit persisted handoffs, which this template does not implement.

## Ownership and changes

The release script owns the ADK backend. Parameter Manager controls its models,
limits and stage instructions. Workflow Builder owns the wrapper, trigger, prompt
and workflow versions. The wrapper dynamically references the published backend.
Updating the backend preserves that reference; replacing its registration requires
checking the wrapper again. Never replace an ADK definition merely to change its icon.

After backend changes, preview the wrapper again. Test recovery, access as another
user and concurrent runs before production use. Enable scheduling only after checking
inputs, quotas, runtime duration and output delivery.

## Automation status

Checked 2026-09-22: the app API returns `workflowAgentDefinition` for existing native
workflows, but the public v1alpha discovery schema does not describe that definition.
This repository does not create or update native wrappers by API. An Existing agent
node payload has not been verified for this app, so use Workflow Builder rather than
inventing fields. A backend release is not completion of the native wrapper.

Source: [Google: Add an existing agent step](https://docs.cloud.google.com/gemini/enterprise/docs/workflow-builder/add-existing-agents).
