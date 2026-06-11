from __future__ import annotations

import tomllib
from pathlib import Path

from agent_xfer import __version__

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_declares_agent_xfer_console_script() -> None:
    project = _pyproject()["project"]
    assert project["name"] == "agent-xfer"
    assert project["version"] == __version__
    assert project["requires-python"] == ">=3.10"
    assert project["scripts"]["agent-xfer"] == "agent_xfer.cli:main"


def test_pyproject_package_discovery_is_limited_to_agent_xfer() -> None:
    tool = _pyproject()["tool"]
    assert tool["setuptools"]["packages"]["find"]["include"] == ["agent_xfer*"]
