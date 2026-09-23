from copy import deepcopy
from unittest.mock import Mock

import pytest
from register import access_groups as groups
from register import agent_sharing as sharing
from register.api_http import ApiError
from register.group_config import GroupConfig, group_config

CONFIG = GroupConfig(
    "customers/C123",
    "ge-dev-basic-users@example.com",
    "owner@example.com",
    "Managed agent access group: p/app/basic",
)
URL = "https://discoveryengine.googleapis.com/v1alpha/projects/p/agents/a"


def group():
    return {
        "name": "groups/123",
        "parent": CONFIG.customer,
        "groupKey": {"id": CONFIG.email},
        "description": CONFIG.marker,
        "labels": {groups.SECURITY_LABEL: ""},
    }


def owner(roles=("MEMBER", "OWNER")):
    return {
        "name": "groups/123/memberships/456",
        "type": "USER",
        "preferredMemberKey": {"id": CONFIG.owner},
        "roles": [{"name": role} for role in roles],
    }


def policy():
    return {
        "version": 3,
        "etag": "original",
        "bindings": [
            {"role": "roles/discoveryengine.agentOwner", "members": ["user:owner@example.com"]},
            {
                "role": sharing.AGENT_USER_ROLE,
                "members": ["user:existing@example.com"],
                "condition": {"title": "temporary", "expression": "true"},
            },
        ],
    }


def test_config_is_opt_in_and_validates_required_fields(monkeypatch):
    assert group_config("p", "app", "basic") is None
    monkeypatch.setenv("GEMINI_AGENT_GROUPS_ENABLED", "yes")
    with pytest.raises(ValueError, match="true or false"):
        group_config("p", "app", "basic")
    monkeypatch.setenv("GEMINI_AGENT_GROUPS_ENABLED", "true")
    with pytest.raises(ValueError, match="CUSTOMER_ID"):
        group_config("p", "app", "basic")
    for key, value in {
        "CUSTOMER_ID": "C123",
        "DOMAIN": "example.com",
        "OWNER_EMAIL": "owner@example.com",
        "PREFIX": "ge-dev",
    }.items():
        monkeypatch.setenv("GEMINI_AGENT_GROUP_" + key, value)
    assert group_config("p", "app", "basic") == CONFIG
    monkeypatch.setenv("GEMINI_AGENT_GROUP_OWNER_EMAIL", "outsider@gmail.com")
    with pytest.raises(ValueError, match="OWNER_EMAIL"):
        group_config("p", "app", "basic")


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_lookup_does_not_treat_failure_as_missing(monkeypatch, status):
    call = Mock(side_effect=ApiError("GET", "lookup", status, "failure"))
    monkeypatch.setattr(groups, "request", call)
    with pytest.raises(ApiError):
        groups.ensure_group(CONFIG, "p")
    assert call.call_count == 1


def test_reuse_preserves_members_without_writes(monkeypatch):
    monkeypatch.setattr(groups, "_lookup", lambda *a: group())
    monkeypatch.setattr(groups, "_membership", lambda *a: owner())
    call = Mock()
    monkeypatch.setattr(groups, "request", call)
    assert groups.ensure_group(CONFIG, "p") == CONFIG.email
    call.assert_not_called()


@pytest.mark.parametrize(
    "field,value", [("parent", "customers/OTHER"), ("description", "unrelated"), ("labels", {})]
)
def test_existing_group_collision_is_not_adopted(monkeypatch, field, value):
    found = group()
    found[field] = value
    monkeypatch.setattr(groups, "_lookup", lambda *a: found)
    call = Mock()
    monkeypatch.setattr(groups, "request", call)
    with pytest.raises(ValueError, match="refusing to adopt"):
        groups.ensure_group(CONFIG, "p")
    call.assert_not_called()


def test_creation_uses_security_label_and_explicit_owner(monkeypatch):
    monkeypatch.setattr(groups, "_lookup", Mock(side_effect=[None, group()]))
    monkeypatch.setattr(groups, "_membership", Mock(side_effect=[None, owner()]))
    call = Mock(return_value={"done": True, "response": {}})
    monkeypatch.setattr(groups, "request", call)
    assert groups.ensure_group(CONFIG, "p") == CONFIG.email
    create, membership = call.call_args_list
    assert "initialGroupConfig=EMPTY" in create.args[1]
    assert groups.SECURITY_LABEL in create.args[3]["labels"]
    assert membership.args[3]["preferredMemberKey"]["id"] == CONFIG.owner
    assert membership.args[3]["roles"] == [{"name": "MEMBER"}, {"name": "OWNER"}]


def test_owner_promotion_is_additive(monkeypatch):
    monkeypatch.setattr(
        groups,
        "_membership",
        Mock(side_effect=[owner(("MEMBER", "MANAGER")), owner()]),
    )
    call = Mock()
    monkeypatch.setattr(groups, "request", call)
    groups._owner(group(), CONFIG, "p")
    assert call.call_args.args[3] == {"addRoles": [{"name": "OWNER"}]}


def test_operation_error_and_polling_are_bounded(monkeypatch):
    with pytest.raises(RuntimeError, match="denied"):
        groups._wait({"done": True, "error": {"message": "denied"}}, "p")
    with pytest.raises(ValueError, match="operation name"):
        groups._wait({"name": "https://untrusted.example/operation"}, "p")
    monkeypatch.setattr(groups.time, "sleep", lambda _: None)
    call = Mock(return_value={"name": "operations/123"})
    monkeypatch.setattr(groups, "request", call)
    with pytest.raises(TimeoutError):
        groups._wait({"name": "operations/123"}, "p")
    assert call.call_count == 60


def test_sharing_preserves_etag_owners_and_conditional_bindings(monkeypatch):
    original = policy()
    verified = deepcopy(original)
    verified["bindings"].append(
        {"role": sharing.AGENT_USER_ROLE, "members": ["group:" + CONFIG.email]}
    )
    monkeypatch.setattr(sharing, "check_sharing", Mock(side_effect=[original, verified]))
    call = Mock()
    monkeypatch.setattr(sharing, "request", call)
    sharing.share_agent(URL, "p", CONFIG.email)
    sent = call.call_args.args[3]["policy"]
    assert sent["etag"] == "original"
    assert sent["bindings"][:2] == original["bindings"]
    assert len(original["bindings"]) == 2
    assert sent == verified


def test_repeat_sharing_does_not_write(monkeypatch):
    existing = policy()
    existing["bindings"].append(
        {"role": sharing.AGENT_USER_ROLE, "members": ["group:" + CONFIG.email]}
    )
    monkeypatch.setattr(sharing, "check_sharing", Mock(return_value=existing))
    call = Mock()
    monkeypatch.setattr(sharing, "request", call)
    sharing.share_agent(URL, "p", CONFIG.email)
    call.assert_not_called()


@pytest.mark.parametrize(
    "agent",
    [{"sharingConfig": {"scope": "ALL_USERS"}}, {"state": "SUSPENDED"}, {"state": "DISABLED"}],
)
def test_unsafe_existing_sharing_fails_without_writes(monkeypatch, agent):
    call = Mock(return_value=agent)
    monkeypatch.setattr(sharing, "request", call)
    with pytest.raises(ValueError):
        sharing.share_agent(URL, "p", CONFIG.email)
    assert call.call_count == 1


def test_missing_etag_and_public_grants_fail(monkeypatch):
    for existing in ({}, {"etag": "x", "bindings": [{"members": ["allAuthenticatedUsers"]}]}):
        monkeypatch.setattr(sharing, "request", Mock(side_effect=[{"state": "ENABLED"}, existing]))
        with pytest.raises(ValueError):
            sharing.check_sharing(URL, "p")


def test_private_agent_can_receive_sharing_but_cannot_pass_final_verification(monkeypatch):
    call = Mock(side_effect=[{"state": "PRIVATE"}, policy()])
    monkeypatch.setattr(sharing, "request", call)
    assert sharing.check_sharing(URL, "p") == policy()
    call.side_effect = [{"state": "PRIVATE"}]
    with pytest.raises(RuntimeError, match="Review/publish"):
        sharing.check_sharing(URL, "p", require_enabled=True)


def test_policy_conflict_does_not_retry_unconditionally(monkeypatch):
    monkeypatch.setattr(sharing, "check_sharing", Mock(return_value=policy()))
    call = Mock(side_effect=ApiError("POST", URL, 409, "conflict"))
    monkeypatch.setattr(sharing, "request", call)
    with pytest.raises(ApiError):
        sharing.share_agent(URL, "p", CONFIG.email)
    assert call.call_count == 1


def test_membership_lookup_is_exact_and_requires_a_user(monkeypatch):
    call = Mock(side_effect=[{"name": owner()["name"]}, owner()])
    monkeypatch.setattr(groups, "request", call)
    assert groups._membership(group(), CONFIG, "p") == owner()
    assert "memberKey.id=owner%40example.com" in call.call_args_list[0].args[1]
    invalid = owner()
    invalid["type"] = "GROUP"
    call.side_effect = [{"name": owner()["name"]}, invalid]
    with pytest.raises(ValueError, match="expected user"):
        groups._membership(group(), CONFIG, "p")


def test_owner_creation_failure_does_not_continue(monkeypatch):
    monkeypatch.setattr(groups, "_lookup", lambda *a: group())
    monkeypatch.setattr(groups, "_membership", lambda *a: None)
    call = Mock(side_effect=ApiError("POST", "membership", 403, "denied"))
    monkeypatch.setattr(groups, "request", call)
    with pytest.raises(ApiError):
        groups.ensure_group(CONFIG, "p")
    assert call.call_count == 1


def test_workflow_registration_shares_backend_and_wrapper(monkeypatch):
    from register import native_workflow, register_agent
    from registry import AGENTS

    spec = AGENTS["recipe_card_workflow"]
    backend = "projects/p/agents/backend"
    wrapper = "projects/p/agents/wrapper"
    monkeypatch.setattr(register_agent, "prepare_access_group", lambda *a: CONFIG.email)
    monkeypatch.setattr(register_agent, "detect_delegated_auth", lambda *a: False)
    monkeypatch.setattr(register_agent, "iter_resources", lambda *a: iter([]))
    monkeypatch.setattr(register_agent, "_request", Mock(return_value={"name": backend}))
    monkeypatch.setattr(native_workflow, "ensure_wrapper", Mock(return_value=wrapper))
    share = Mock()
    monkeypatch.setattr(register_agent, "share_agent", share)
    assert (
        register_agent.register_agent(
            spec.package_name, "app", "p", spec, "projects/p/locations/us/reasoningEngines/r"
        )
        == wrapper
    )
    assert [c.args[0].rsplit("/", 1)[-1] for c in share.call_args_list] == ["backend", "wrapper"]
    assert all(c.args[2] == CONFIG.email for c in share.call_args_list)
    payload = register_agent._request.call_args.args[3]
    assert payload["sharingConfig"] == {"scope": "RESTRICTED"}


def test_group_failure_stops_release_before_packaging(monkeypatch):
    import sys

    import release_dev

    monkeypatch.setattr(sys, "argv", ["release_dev.py", "--agent", "basic_assistant"])
    monkeypatch.setattr(release_dev, "load_environment", lambda *a: None)
    monkeypatch.setattr(release_dev, "require_dev_environment", lambda **kw: ("p", "us", "gs://b"))
    monkeypatch.setattr(release_dev, "runtime_override", lambda *a: None)
    monkeypatch.setattr(release_dev, "ensure_dev_prerequisites", lambda *a: None)
    monkeypatch.setattr(
        release_dev, "prepare_access_group", Mock(side_effect=ValueError("directory"))
    )
    package = Mock()
    monkeypatch.setattr(release_dev, "package_agent", package)
    with pytest.raises(ValueError, match="directory"):
        release_dev.main()
    package.assert_not_called()
