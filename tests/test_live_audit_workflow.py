"""Exercise the workflow's shell steps without Google credentials or network access."""

import json
import os
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

WORKFLOW = (Path(__file__).parents[1] / ".github/workflows/live-audit.yml").read_text()


def run_step(name, tmp_path, extra_env):
    step = WORKFLOW.split(f"      - name: {name}\n", 1)[1].split("\n      - ", 1)[0]
    script = dedent(step.split("        run: |\n", 1)[1])
    return subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        env={**os.environ, **extra_env},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "credential",
    [
        "",
        "broken-json",
        "[]",
        "null",
        '"text"',
        "{}",
        json.dumps(
            {
                "type": "service_account",
                "client_email": "test@example.com",
                "private_key": " ",
                "token_uri": "https://example.com/token",
            }
        ),
    ],
)
def test_invalid_credentials_are_not_exported(tmp_path, credential):
    env_file = tmp_path / "env"
    result = run_step(
        "Configure Google credentials",
        tmp_path,
        {
            "GOOGLE_CREDENTIALS_JSON": credential,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ENV": str(env_file),
        },
    )
    assert result.returncode != 0
    assert "XPRESS_GOOGLE_CREDENTIALS" in result.stderr
    assert not env_file.exists()


def test_structurally_valid_credentials_are_exported(tmp_path):
    env_file = tmp_path / "env"
    credential = json.dumps(
        {
            "type": "service_account",
            "client_email": "test@example.com",
            "private_key": "test-placeholder",
            "token_uri": "https://example.com",
        }
    )
    result = run_step(
        "Configure Google credentials",
        tmp_path,
        {
            "GOOGLE_CREDENTIALS_JSON": credential,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ENV": str(env_file),
        },
    )
    assert result.returncode == 0, result.stderr
    assert str(tmp_path / "google-credentials.json") in env_file.read_text()
    assert "test-placeholder" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("output", "exit_code", "success"),
    [
        ('echo \'{"status":"ok"}\'', 0, True),
        ('echo \'{"status":"partial"}\'', 7, False),
        (":", 0, False),
    ],
)
def test_audit_pipeline_preserves_failure(tmp_path, output, exit_code, success):
    uv = tmp_path / "uv"
    uv.write_text(f"#!/bin/bash\n{output}\nexit {exit_code}\n")
    uv.chmod(0o755)
    result = run_step(
        "Run read-only live audit",
        tmp_path,
        {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
    )
    assert (result.returncode == 0) is success
