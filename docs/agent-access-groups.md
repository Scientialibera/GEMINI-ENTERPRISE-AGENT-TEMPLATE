# Agent access groups

Deployment can create one Cloud Identity security group per agent or workflow and
grant it permission to use that registration. The configured owner adds and
removes users in Google Groups afterward. Redeployment preserves memberships.

## Setup

This requires a managed Google Workspace or Cloud Identity domain. A personal
Gmail account and Cloud project Owner role are not enough. Ask the directory
administrator to enable the Cloud Identity API in the deployment project and
provide ADC credentials authorized to create security groups and manage their
memberships. The helper creates empty groups, which requires domain-admin
authority. It does not configure domain-wide delegation, create credentials or
grant directory-admin roles. Registration also requires permission to read and
set IAM policies on the target agents.

Add these deployment-only settings to `dev/.env.dev`:

```dotenv
GEMINI_AGENT_GROUPS_ENABLED=true
GEMINI_AGENT_GROUP_CUSTOMER_ID=C012abcde
GEMINI_AGENT_GROUP_DOMAIN=example.com
GEMINI_AGENT_GROUP_OWNER_EMAIL=agent-owner@example.com
GEMINI_AGENT_GROUP_PREFIX=ge-dev
```

Replace all example values. The customer ID comes from the Workspace Admin
console, not the Cloud project number. Choose a prefix unique to this app and
environment. For `basic_assistant`, this example creates
`ge-dev-basic-assistant-users@example.com`. The complete local part must fit
within 64 characters. The owner must be a user in the configured domain.

Run the normal release command:

```powershell
uv run --group dev python dev/release_dev.py --agent basic_assistant
```

To add sharing to an already deployed agent without redeploying its runtime:

```powershell
uv run --group dev python dev/register/register_agent.py --agent basic_assistant
```

The helper prints the group email and its Google Groups membership URL. The
owner can add users there or use the Workspace Admin console. Group membership
and IAM changes can take time to propagate. Users still need a Gemini Enterprise
license and access to the app; group membership alone does not provide those.
Delegated tools still enforce each user's downstream API permissions and consent.

## What deployment changes

The release preflight creates or checks the group before packaging and deploying.
Registration checks it again so standalone registration has the same behavior.
An existing group is reused only when its customer, email, security label and
project/app/package description marker match. Unrelated groups are not adopted.
Keep that marker unchanged. The configured user is added as owner if necessary;
other owners and members are never removed. Changing OWNER_EMAIL adds a new
owner; remove the old owner manually if required.

Registration adds `roles/discoveryengine.agentUser` to the group's binding on
the individual agent, not the project or runtime. This grants use, not prompt
editing, deployment or group administration. Workflow registrations apply the
same group to the native wrapper and its ADK backend. Existing schedules and
workflow prompts remain unchanged. A wrapper can reference other resources you
added manually; their permissions remain your responsibility.

New registrations use restricted sharing. Existing organization-wide sharing or
public IAM grants cause an error instead of being silently replaced. Review and
restrict those grants in the console before retrying. Disabled or suspended
registrations require a manual state review; the helper does not turn them on.
Private registrations can receive the requested group binding. The final check
also requires an enabled state: if sharing leaves the agent private, the command
reports incomplete registration and asks you to review/publish it in the console.
It does not silently activate a draft schedule.

Existing direct grants, conditional grants and owner bindings are preserved.
This is additive group-based sharing, not an exclusive group allowlist. Audit
existing agent/app/project permissions separately if group removal must revoke
all access. IAM writes include the current etag; concurrent changes fail rather
than overwriting another administrator's update. Do not run concurrent releases
for the same agent.

## Recovery and verification

Group creation, owner assignment and agent sharing are separate operations. If
one fails, deployment reports failure; it does not roll back groups, delete
members or broaden access. Correct the reported issue and rerun registration.
For a pending Cloud Identity operation, inspect its completion before retrying.
A permission error is never treated as a missing group. Disabling the feature
or using `--skip-register` leaves existing groups and grants in place.

Changing the prefix/domain creates a different group and retains the old IAM
grant. Treat that as an access migration: remove the old grant deliberately
after testing. Deleted or recreated groups also need an IAM access review.

The helper reads back the group owner and IAM binding. Unit tests cover API
failures and policy preservation; these are not a substitute for a tenant test.
Before rollout, add one licensed test user with app access and confirm the agent
works. Test a second user without membership, then remove the first user and
retest after propagation. For workflows, test the wrapper and its backend.

The agent-level IAM endpoint was reachable in the development project and the
Agent User role was confirmed through Google's IAM API. That endpoint is absent
from the current public Discovery Engine discovery schema, so this integration
needs tenant validation. No live managed-domain group test has been completed.

## References

- [Share agents in Gemini Enterprise](https://docs.cloud.google.com/gemini/enterprise/docs/share-custom-agents)
- [Create security groups](https://docs.cloud.google.com/identity/docs/how-to/update-group-to-security-group)
- [Cloud Identity group creation API](https://docs.cloud.google.com/identity/docs/reference/rest/v1/groups/create)
- [App access controls](https://docs.cloud.google.com/gemini/enterprise/docs/iam-policy-for-apps)
