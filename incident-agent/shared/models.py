from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RiskLevel = Literal["low", "medium", "high"]


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["datadog", "prometheus", "unknown"]
    service: str
    alert_name: str
    timestamp: datetime
    severity: str
    labels: dict[str, str] = Field(default_factory=dict)
    fingerprint: str


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_level: RiskLevel
    severity: str
    summary: str
    suspected_cause: str | None = None
    recommended_runbooks: list[str] = Field(default_factory=list)


class RemediationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    risk_level: RiskLevel
    requires_approval: bool = False


class RemediationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_level: RiskLevel
    steps: list[RemediationStep]
    approval_required: bool = False


class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    alert_fingerprint: str
    status: Literal["new", "awaiting_approval", "remediated", "failed"]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    triage: TriageResult | None = None
    remediation: RemediationPlan | None = None

