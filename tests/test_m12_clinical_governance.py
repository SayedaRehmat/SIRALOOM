from datetime import datetime, timezone
from backend.app.infrastructure.db.models import ConfirmationRecord, FollowUpPlan, SecondaryFindingDecision

def test_m12_models_expose_versioned_confirmation_and_policy_governance():
    confirmation = ConfirmationRecord(required=True, status="PENDING", version=2, method="Sanger")
    assert confirmation.required is True
    assert confirmation.status == "PENDING"
    assert confirmation.version == 2
    secondary = SecondaryFindingDecision(policy_name="LAB_SECONDARY_FINDINGS", policy_version="1.0", consent_status="ACCEPTED", disposition="REPORT", status="FINAL")
    assert secondary.policy_name == "LAB_SECONDARY_FINDINGS"
    assert secondary.policy_version == "1.0"
    assert secondary.consent_status == "ACCEPTED"
    assert secondary.disposition == "REPORT"

def test_m12_followup_completion_fields_are_explicit():
    now = datetime.now(timezone.utc)
    plan = FollowUpPlan(action_type="GENETIC_COUNSELLING", status="COMPLETED", completed_at=now)
    assert plan.status == "COMPLETED"
    assert plan.completed_at == now
