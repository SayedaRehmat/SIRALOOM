from backend.app.inheritance import FamilyObservation, assess_model, fingerprint, normalize_model


def test_m10_model_aliases_and_fingerprint_are_deterministic():
    assert normalize_model("autosomal dominant") == "AD"
    observations = [
        FamilyObservation("MOTHER", "FEMALE", "UNAFFECTED", "0/0", "HOM_REF"),
        FamilyObservation("PROBAND", "MALE", "AFFECTED", "0/1", "HET"),
    ]
    assert fingerprint(observations) == fingerprint(list(reversed(observations)))


def test_m10_ad_consistency_requires_reviewable_family_observations():
    observations = [
        FamilyObservation("MOTHER", "FEMALE", "UNAFFECTED", "0/0", "HOM_REF"),
        FamilyObservation("PROBAND", "MALE", "AFFECTED", "0/1", "HET"),
    ]
    result = assess_model("AD", observations)
    assert result["status"] == "CONSISTENT"
    assert result["supporting_observations"] == 2
    assert result["contradictory_observations"] == 0


def test_m10_ad_contradiction_is_explicit_not_silent():
    observations = [
        FamilyObservation("MOTHER", "FEMALE", "UNAFFECTED", "0/1", "HET"),
        FamilyObservation("PROBAND", "MALE", "AFFECTED", "0/1", "HET"),
    ]
    result = assess_model("AD", observations)
    assert result["status"] == "CONTRADICTED"
    assert result["contradictory_observations"] == 1


def test_m10_ar_single_heterozygous_affected_member_is_not_called_consistent():
    observations = [FamilyObservation("PROBAND", "FEMALE", "AFFECTED", "0/1", "HET")]
    result = assess_model("AR", observations)
    assert result["status"] == "CONTRADICTED"
    assert result["contradictory_observations"] == 1


def test_m10_no_genotype_data_is_insufficient():
    observations = [FamilyObservation("PROBAND", "MALE", "AFFECTED", None, None)]
    result = assess_model("AD", observations)
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["score"] == 0


def test_m10_supported_models_are_explicit():
    assert {normalize_model(x) for x in ["AD", "AR", "XL", "mito", "de_novo"]} == {
        "AD", "AR", "X_LINKED", "MITOCHONDRIAL", "DE_NOVO"
    }
