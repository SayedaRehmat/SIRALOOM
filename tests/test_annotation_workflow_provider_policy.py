from pathlib import Path

import yaml

from backend.app.domain.analysis_resource_profiles import get_analysis_resource_profile
from backend.app.domain.resource_profile_resolver import _effective_preferred_providers
from backend.app.domain.resource_capabilities import ANNOTATION_ENGINE


def test_variant_workflow_manifest_uses_governed_annotation_provider_policy():
    manifest_path = Path(__file__).parents[1] / "workflows" / "variant" / "v1.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    annotation_step = next(
        step for step in manifest["steps"] if step["id"] == "annotate"
    )
    assert annotation_step["capability"] == ANNOTATION_ENGINE
    assert set(annotation_step["providers"]) == {"VEP", "GeneBe"}
    assert annotation_step["provider_selection"] == {
        "source": "organization-approved-analysis-resource-profile",
        "deployment_policy": {
            "LABORATORY": ["VEP"],
            "TRIAL_PUBLIC": ["GeneBe"],
        },
        "fallback": "none",
    }


def test_variant_workflow_manifest_provider_policy_matches_runtime_resolution():
    manifest_path = Path(__file__).parents[1] / "workflows" / "variant" / "v1.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    annotation_step = next(
        step for step in manifest["steps"] if step["id"] == "annotate"
    )
    profile = get_analysis_resource_profile("WES_GRCh38_STANDARD")
    requirement = next(
        item for item in profile.requirements
        if item.capability == ANNOTATION_ENGINE
    )

    for deployment, expected in (
        ("LABORATORY", ("VEP",)),
        ("TRIAL_PUBLIC", ("GENEBE",)),
    ):
        assert tuple(
            provider.upper()
            for provider in annotation_step["provider_selection"]["deployment_policy"][deployment]
        ) == _effective_preferred_providers(
            requirement, deployment_profile_type=deployment
        )
        assert _effective_preferred_providers(
            requirement, deployment_profile_type=deployment
        ) == expected
