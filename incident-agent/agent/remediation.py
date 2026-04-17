from __future__ import annotations

from shared.config import settings
from shared.models import Alert, RemediationPlan, RemediationStep, TriageResult


async def plan_remediation(alert: Alert, triage: TriageResult) -> RemediationPlan:
    """
    Create an MVP remediation plan from the triage result.

    MVP behavior:
      - `low` risk => steps execute as stubs immediately
      - `medium/high` => if `REQUIRE_APPROVAL` is true, pause for Slack approval (stub)
    """

    requires_approval = triage.risk_level in {"medium", "high"}
    approval_required = bool(settings.REQUIRE_APPROVAL and requires_approval)

    # Step 1 is read-only (context gathering) => no approval.
    steps: list[RemediationStep] = [
        RemediationStep(
            title="Assess incident context (stub)",
            description=(
                f"Use triage summary + recommended runbooks to draft a safe remediation approach "
                f"(alert={alert.alert_name}, service={alert.service})."
            ),
            risk_level=triage.risk_level,
            requires_approval=False,
        ),
        RemediationStep(
            title="Execute remediation (stub)",
            description=(
                f"Would perform remediation actions for service={alert.service} "
                f"(risk={triage.risk_level})."
            ),
            risk_level=triage.risk_level,
            requires_approval=approval_required,
        ),
    ]

    return RemediationPlan(
        risk_level=triage.risk_level,
        steps=steps,
        approval_required=approval_required,
    )

