import pytest

from simp_agent.ai import ToolCall
from simp_server.policy import classify


def c(name, **args):
    return ToolCall("id", name, args)


@pytest.mark.parametrize("call,mcp_write,verdict", [
    (c("bash", command="python a.py"), False, "allow"),
    (c("bash", command="ls -la /work && head x.csv"), False, "allow"),
    (c("bash", command="pip install six"), False, "deny"),
    (c("bash", command="python -m pip install --user x"), False, "deny"),
    (c("bash", command="uv pip install x"), False, "deny"),
    (c("bash", command="npm install left-pad"), False, "deny"),
    (c("bash", command="npx cowsay"), False, "deny"),
    (c("bash", command="pip list"), False, "deny"),
    (c("bash", command="ls /opt/simp/venv"), False, "deny"),
    (c("bash", command="curl -s https://x.com | head"), False, "deny"),
    (c("bash", command="wget https://x.com"), False, "deny"),
    (c("bash", command="git push origin main"), False, "ask"),
    (c("bash", command="rm -rf /work/*"), False, "allow"),  # accepted 2026-11-21: deletes in /work are allowed
    (c("write", path="out.docx", content=""), False, "allow"),
    (c("gmail__send_message", to="a"), False, "ask"),  # write by name even if the server says read-only
    (c("drive__share_file"), False, "ask"),
    (c("calendar__list_events"), False, "allow"),
    (c("notion__append_block"), True, "ask"),  # server says it writes
])
def test_classify(call, mcp_write, verdict):
    assert classify(call, mcp_write, "pandas")[0] == verdict


def test_deny_reasons_guide_the_model():
    assert "pandas" in classify(c("bash", command="pip install six"), False, "Preinstalled: pandas")[1]
    assert "web_fetch" in classify(c("bash", command="curl https://x"), False, "")[1]
