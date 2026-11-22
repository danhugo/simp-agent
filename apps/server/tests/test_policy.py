import pytest

from simp_agent.ai import ToolCall
from simp_server.policy import classify


def c(name, **args):
    return ToolCall("id", name, args)


def bash(cmd):
    return c("bash", command=cmd)


@pytest.mark.parametrize("cmd,verdict", [
    ("python a.py", "allow"),
    ("ls -la /work && head x.csv", "allow"),
    ("rm -rf /work/*", "allow"),  # accepted 2026-11-21: deletes in /work are allowed
    ("git push origin main", "allow"),  # no network: it fails by itself, nothing to ask
    # keyword not in command position: not a match (item 3)
    ("grep -rn curl notes.md", "allow"),
    ("cat apt.txt", "allow"),
    ("ls nc/", "allow"),
    ("echo 'use pip install to add it'", "allow"),
    ("python /opt/simp/venv/bin/x.py", "allow"),
    # real installs / browsing / network
    ("pip install six", "deny"),
    ("pip3 install --user x", "deny"),
    ("python -m pip install x", "deny"),
    ("cd /work && /opt/simp/venv/bin/pip install x", "deny"),
    ("uv pip install x", "deny"),
    ("npm install left-pad", "deny"),
    ("npx cowsay", "deny"),
    ("sudo apt-get install jq", "deny"),
    ("env A=1 pip install x", "deny"),
    ("pip list", "deny"),
    ("ls /opt/simp/venv", "deny"),
    ("ls /opt/simp", "deny"),
    ("mkdir -p /tmp/ds && ls /opt/simp/skills/pptx/scripts", "allow"),
    ("find /opt/simp/skills -name '*.py'", "allow"),
    ("curl -s https://x.com | head", "deny"),
    ("cd /work && curl https://x.com", "deny"),
    ("x=$(wget -qO- https://x.com)", "deny"),
])
def test_bash(cmd, verdict):
    assert classify(bash(cmd), False, "pandas")[0] == verdict


@pytest.mark.parametrize("name,mcp_write,verdict", [
    ("gmail__send_message", False, "ask"),  # write by name even if the server says read-only
    ("drive__share_file", False, "ask"),
    ("gmail__create_draft", False, "ask"),
    ("calendar__update_event", False, "ask"),
    ("drive__trash_file", False, "ask"),
    ("gmail__list_drafts", False, "allow"),  # read tools whose names merely contain a write word (item 3)
    ("drive__get_file_permissions", False, "allow"),
    ("slack__list_posts", False, "allow"),
    ("calendar__list_events", False, "allow"),
    ("notion__append_block", True, "ask"),  # the server says it writes
    ("notion__fetch_page", True, "ask"),
])
def test_mcp(name, mcp_write, verdict):
    assert classify(c(name), mcp_write, "")[0] == verdict


def test_network_commands_allowed_when_sandbox_has_network():
    """Item 5: dev (docker, egress open) has real network, so do not tell the model there is none."""
    assert classify(bash("curl https://x.com"), False, "", net_blocked=False)[0] == "allow"
    assert classify(bash("pip install six"), False, "", net_blocked=False)[0] == "deny"  # libraries still fixed


def test_deny_reasons_guide_the_model():
    assert "pandas" in classify(bash("pip install six"), False, "Preinstalled: pandas")[1]
    assert "web_fetch" in classify(bash("curl https://x"), False, "")[1]
