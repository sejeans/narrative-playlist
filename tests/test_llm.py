import json
from types import SimpleNamespace

import pytest

from narrative_playlist import config, llm


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LLM_BACKEND", "cli")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return calls_out.pop(0)

    calls_out = []
    monkeypatch.setattr(llm.subprocess, "run", run)
    return calls, calls_out


def _ok(obj):
    return SimpleNamespace(returncode=0, stdout=json.dumps({"is_error": False, "structured_output": obj}), stderr="")


def test_cli_backend_returns_structured_output(cli):
    calls, outs = cli
    outs.append(_ok({"stage": "설렘"}))
    d = llm.structured_call(model="claude-haiku-5-5", system="S", user="가사...", tool_name="t", tool_desc="d", schema={"type": "object"})
    assert d == {"stage": "설렘"}
    cmd, kw = calls[0]
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--json-schema" in cmd and "--system-prompt" in cmd
    assert kw["input"] == "가사..."  # 긴 가사는 인자 대신 stdin 으로
    assert "ANTHROPIC_API_KEY" not in kw["env"]  # 구독 대신 API 과금되지 않게


def test_cli_error_surfaces_reason(cli):
    _, outs = cli
    outs.append(SimpleNamespace(returncode=1, stdout=json.dumps({"is_error": True, "result": "usage limit reached"}), stderr=""))
    with pytest.raises(RuntimeError, match="usage limit"):
        llm.structured_call(model="m", system="", user="", tool_name="t", tool_desc="", schema={})


def test_cli_missing(monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "cli")
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="찾을 수 없습니다"):
        llm.structured_call(model="m", system="", user="", tool_name="t", tool_desc="", schema={})


@pytest.mark.parametrize("setting,key,expected", [("auto", None, "cli"), ("auto", "k", "api"), ("cli", "k", "cli"), ("api", None, "api")])
def test_backend_selection(monkeypatch, setting, key, expected):
    monkeypatch.setattr(config, "LLM_BACKEND", setting)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", key)
    assert llm.backend() == expected
