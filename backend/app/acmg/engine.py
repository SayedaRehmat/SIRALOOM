"""Conservative ACMG/AMP baseline decision-support engine.

Important boundary:
- Criterion assignment is not guessed from a generic annotation score.
- Biological evidence evaluators live above/beside this module.
- This module validates explicit criterion assessments and combines them using
  versioned baseline rules.
- The result is a PROPOSED classification until a human reviewer approves it.
"""
from dataclasses import dataclass, field
from typing import Any

from .rules import (
    ACMG2015BaselineProfile,
    BENIGN_CRITERIA,
    CriterionDirection,
    PATHOGENIC_CRITERIA,
    RuleProfile,
    STRENGTH_TO_POINTS,
    validate_direction,
    validate_strength,
)

@dataclass(frozen=True)
class CriterionAssessment:
    criterion: str
    strength: str
    direction: str
    status: str = "PROPOSED"
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ClassificationResult:
    classification: str
    state: str
    framework: str
    framework_version: str
    profile_id: str
    profile_version: str
    criteria: tuple[CriterionAssessment, ...]
    rationale: tuple[str, ...]

class ACMGEngine:
    def __init__(self, profile: RuleProfile = ACMG2015BaselineProfile):
        self.profile = profile

    def validate_assessments(self, assessments: list[CriterionAssessment]) -> None:
        seen: set[str] = set()
        for a in assessments:
            validate_strength(a.criterion, a.strength)
            validate_direction(a.criterion, a.direction)
            if a.criterion in seen:
                raise ValueError(f"Duplicate ACMG criterion assessment: {a.criterion}")
            seen.add(a.criterion)

    @staticmethod
    def _counts(assessments: list[CriterionAssessment], direction: str) -> dict[str, int]:
        result = {"VERY_STRONG": 0, "STRONG": 0, "MODERATE": 0, "SUPPORTING": 0}
        for a in assessments:
            if a.direction == direction and a.strength in result:
                result[a.strength] += 1
        return result

    def classify(self, assessments: list[CriterionAssessment]) -> ClassificationResult:
        self.validate_assessments(assessments)
        p = self._counts(assessments, CriterionDirection.PATHOGENIC)
        b = self._counts(assessments, CriterionDirection.BENIGN)
        codes = {a.criterion for a in assessments}
        rationale: list[str] = []

        # A pathogenic/benign direction conflict is never silently resolved.
        if any(a.direction == CriterionDirection.PATHOGENIC for a in assessments) and any(a.direction == CriterionDirection.BENIGN for a in assessments):
            rationale.append("Conflicting pathogenic and benign evidence is present; human review is required.")
            return ClassificationResult(
                "VUS", "REQUIRES_REVIEW", self.profile.framework, self.profile.framework_version,
                self.profile.profile_id, self.profile.version, tuple(assessments), tuple(rationale)
            )

        if "BA1" in codes:
            rationale.append("BA1 is present as a standalone benign criterion.")
            return ClassificationResult(
                "BENIGN", "PROPOSED", self.profile.framework, self.profile.framework_version,
                self.profile.profile_id, self.profile.version, tuple(assessments), tuple(rationale)
            )

        if b["STRONG"] >= 2:
            rationale.append("At least two strong benign criteria are present.")
            return ClassificationResult(
                "BENIGN", "PROPOSED", self.profile.framework, self.profile.framework_version,
                self.profile.profile_id, self.profile.version, tuple(assessments), tuple(rationale)
            )

        if b["STRONG"] >= 1 and b["SUPPORTING"] >= 1:
            rationale.append("One strong plus at least one supporting benign criterion is present.")
            return ClassificationResult(
                "LIKELY_BENIGN", "PROPOSED", self.profile.framework, self.profile.framework_version,
                self.profile.profile_id, self.profile.version, tuple(assessments), tuple(rationale)
            )

        if b["SUPPORTING"] >= 2:
            rationale.append("At least two supporting benign criteria are present.")
            return ClassificationResult(
                "LIKELY_BENIGN", "PROPOSED", self.profile.framework, self.profile.framework_version,
                self.profile.profile_id, self.profile.version, tuple(assessments), tuple(rationale)
            )

        # Standard ACMG/AMP 2015 pathogenic combinations.
        pathogenic = False
        likely_pathogenic = False

        if p["VERY_STRONG"] >= 1 and p["STRONG"] >= 1:
            pathogenic = True; rationale.append("Very strong + strong pathogenic evidence.")
        elif p["VERY_STRONG"] >= 1 and p["MODERATE"] >= 2:
            pathogenic = True; rationale.append("Very strong + at least two moderate pathogenic criteria.")
        elif p["VERY_STRONG"] >= 1 and p["MODERATE"] >= 1 and p["SUPPORTING"] >= 1:
            pathogenic = True; rationale.append("Very strong + moderate + supporting pathogenic evidence.")
        elif p["VERY_STRONG"] >= 1 and p["SUPPORTING"] >= 2:
            pathogenic = True; rationale.append("Very strong + at least two supporting pathogenic criteria.")
        elif p["STRONG"] >= 2:
            pathogenic = True; rationale.append("At least two strong pathogenic criteria.")
        elif p["STRONG"] >= 1 and p["MODERATE"] >= 3:
            pathogenic = True; rationale.append("Strong + at least three moderate pathogenic criteria.")
        elif p["STRONG"] >= 1 and p["MODERATE"] >= 2 and p["SUPPORTING"] >= 2:
            pathogenic = True; rationale.append("Strong + at least two moderate + at least two supporting pathogenic criteria.")
        elif p["STRONG"] >= 1 and p["MODERATE"] >= 1 and p["SUPPORTING"] >= 4:
            pathogenic = True; rationale.append("Strong + moderate + at least four supporting pathogenic criteria.")

        if not pathogenic:
            if p["VERY_STRONG"] >= 1 and p["MODERATE"] >= 1:
                likely_pathogenic = True; rationale.append("Very strong + moderate pathogenic evidence.")
            elif p["VERY_STRONG"] >= 1 and p["SUPPORTING"] >= 1:
                likely_pathogenic = True; rationale.append("Very strong + supporting pathogenic evidence.")
            elif p["STRONG"] >= 1 and p["MODERATE"] in {1, 2}:
                likely_pathogenic = True; rationale.append("Strong + one or two moderate pathogenic criteria.")
            elif p["STRONG"] >= 1 and p["SUPPORTING"] >= 2:
                likely_pathogenic = True; rationale.append("Strong + at least two supporting pathogenic criteria.")
            elif p["MODERATE"] >= 3:
                likely_pathogenic = True; rationale.append("At least three moderate pathogenic criteria.")
            elif p["MODERATE"] >= 2 and p["SUPPORTING"] >= 2:
                likely_pathogenic = True; rationale.append("At least two moderate + at least two supporting pathogenic criteria.")
            elif p["MODERATE"] >= 1 and p["SUPPORTING"] >= 4:
                likely_pathogenic = True; rationale.append("At least one moderate + at least four supporting pathogenic criteria.")

        classification = "PATHOGENIC" if pathogenic else "LIKELY_PATHOGENIC" if likely_pathogenic else "VUS"
        if not rationale:
            rationale.append("No baseline ACMG/AMP 2015 combination rule was satisfied.")
        return ClassificationResult(
            classification,
            "PROPOSED",
            self.profile.framework,
            self.profile.framework_version,
            self.profile.profile_id,
            self.profile.version,
            tuple(assessments),
            tuple(rationale),
        )

    def build_assessment_from_explicit_evidence(
        self,
        *,
        criterion: str,
        strength: str,
        direction: str,
        evidence_ids: list[str],
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> CriterionAssessment:
        validate_strength(criterion, strength)
        validate_direction(criterion, direction)
        return CriterionAssessment(
            criterion=criterion,
            strength=strength,
            direction=direction,
            status="PROPOSED",
            evidence_ids=tuple(evidence_ids),
            reason=reason,
            metadata=metadata or {},
        )
