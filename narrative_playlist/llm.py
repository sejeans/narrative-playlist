"""LLM 호출 공통부. 항상 스키마에 맞는 JSON(dict)을 돌려준다.

백엔드 두 가지
- cli : 내 PC에 로그인된 Claude Code CLI(`claude -p`)를 호출한다. Claude 구독 플랜(Pro/Max) 사용량으로 처리되고 API 키가 필요 없다.
- api : Anthropic API 키로 직접 호출한다. 사용한 만큼 과금.

NP_LLM_BACKEND=auto(기본)면 ANTHROPIC_API_KEY 가 있을 때 api, 없으면 cli.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from . import config

_client = None


def backend() -> str:
    b = config.LLM_BACKEND
    if b == "auto":
        return "api" if config.ANTHROPIC_API_KEY else "cli"
    return b


def structured_call(
    *, model: str, system: str, user: str, tool_name: str, tool_desc: str, schema: dict, max_tokens: int = 1500
) -> dict:
    if backend() == "cli":
        return _cli_call(model=model, system=system, user=user, schema=schema)
    return _api_call(
        model=model, system=system, user=user, tool_name=tool_name, tool_desc=tool_desc, schema=schema, max_tokens=max_tokens
    )


# ---------------------------------------------------------------- Claude Code CLI (구독 플랜)


def _cli_model(model: str) -> str:
    """API 모델 이름을 CLI 별칭으로. 플랜에 따라 쓸 수 있는 버전이 달라서 별칭이 안전하다."""
    for alias in ("haiku", "sonnet", "opus"):
        if model.startswith(f"claude-{alias}"):
            return alias
    return model


def _cli_call(*, model: str, system: str, user: str, schema: dict) -> dict:
    exe = shutil.which(config.CLAUDE_CLI)
    if not exe:
        raise RuntimeError(
            "Claude Code CLI(claude)를 찾을 수 없습니다. 설치 후 `claude` 를 한 번 실행해 Claude 계정으로 로그인하세요.\n"
            "설치: https://code.claude.com/docs/en/setup"
        )
    cmd = [
        exe, "-p", "입력으로 받은 곡 정보를 분석하고, 지정된 JSON 형식으로만 답하라.",
        "--output-format", "json",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--system-prompt", system,
        "--model", _cli_model(model),
        # 이 작업엔 파일·셸·MCP 도구가 필요 없다. 전부 끄고 설정·스킬도 읽지 않게.
        "--tools", "",
        "--disallowedTools", "mcp__*",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    # ANTHROPIC_API_KEY 가 환경에 있으면 CLI가 구독 대신 API 키로 과금하므로 빼고 실행한다.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    workdir = config.CACHE_DIR / "cli-workdir"  # 프로젝트의 CLAUDE.md 등을 읽지 않도록 빈 폴더에서 실행
    workdir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        cmd, input=user, capture_output=True, text=True, encoding="utf-8",
        env=env, cwd=workdir, timeout=config.CLI_TIMEOUT,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        msg = (proc.stderr or proc.stdout).strip()[:500]
        raise RuntimeError(f"claude CLI 실행 실패 (exit {proc.returncode}): {msg}")
    if out.get("is_error") or "structured_output" not in out:
        # 사용량 한도 초과, 로그인 만료 등은 result 에 사유가 온다
        raise RuntimeError(f"claude CLI 오류: {str(out.get('result'))[:500]}")
    return out["structured_output"]


# ---------------------------------------------------------------- Anthropic API (키 사용)


def _api_call(*, model, system, user, tool_name, tool_desc, schema, max_tokens) -> dict:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY 가 설정되지 않았습니다. 구독 플랜을 쓰려면 NP_LLM_BACKEND=cli 로 두세요.")
        import anthropic

        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=3)
    resp = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=[{"name": tool_name, "description": tool_desc, "input_schema": schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    raise RuntimeError(f"모델이 {tool_name} 결과를 돌려주지 않았습니다 (stop_reason={resp.stop_reason}).")
