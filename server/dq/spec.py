"""AgentSpec: the data contract for an agent. The catalog YAML is validated against this model at start-up,
so a typo in a spec fails fast with a clear message instead of failing in front of a customer."""
from __future__ import annotations

import pathlib
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

CATALOG_DIR = pathlib.Path(__file__).resolve().parent.parent / "catalog"
VERTICALS = ["Fintech", "Manufacturing", "Wholesale", "Retail", "E-commerce", "Healthcare", "Digital Marketing", "Data Automation"]


class EvalCase(BaseModel):
    ask: str
    expect_tool: str | None = None
    expect: str = ""


class DemoStep(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class Demo(BaseModel):
    ask: str
    script: list[DemoStep] = Field(default_factory=list)
    reply: str = ""
    # generic = the simulated model fills {machine}, {part}, {technician}... from the request and earlier tool results,
    # and writes its reply from the tools' "summary" fields. Used by agents that run on live events.
    generic: bool = False


class AgentSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")
    name: str
    vertical: str
    tier: Literal["hero", "standard"] = "standard"
    tagline: str
    problem: str
    users: str
    trigger: str
    model: str = "flash"
    thinking: Literal["low", "medium", "high"] = "medium"
    autonomy: Literal["suggest", "approve", "auto"] = "approve"
    tools: list[str]
    approvals: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    instruction: str
    kpis: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    evals: list[EvalCase] = Field(default_factory=list)
    demo: Demo

    @model_validator(mode="after")
    def _check(self):
        if self.vertical not in VERTICALS:
            raise ValueError(f"{self.id}: unknown vertical {self.vertical!r}")
        missing = set(self.approvals) - set(self.tools)
        if missing:
            raise ValueError(f"{self.id}: approvals {sorted(missing)} are not in tools")
        return self

    @property
    def agent_name(self) -> str:
        """ADK agent names must be valid identifiers."""
        return self.id.replace("-", "_")


def load_catalog(directory: pathlib.Path = CATALOG_DIR) -> dict[str, AgentSpec]:
    specs: dict[str, AgentSpec] = {}
    for path in sorted(directory.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            spec = AgentSpec(**raw)
            if spec.id in specs:
                raise ValueError(f"duplicate agent id {spec.id} in {path.name}")
            specs[spec.id] = spec
    return specs
