import gzip
from pathlib import Path
from uuid import uuid4

from backend.app.adapters.evidence.clinvar import ClinVarProviderError, ClinVarVCVProvider
from backend.app.domain.resource_execution import ResolvedResourceExecution
from backend.app.domain.resource_source_contract import ResourceExecutionContract


def _resolved(path: Path) -> ResolvedResourceExecution:
    resource_id = uuid4()
    qualification_id = uuid4()
    contract = ResourceExecutionContract(
        provider_id="NCBI ClinVar",
        provider_version="release-xml-v1",
        access_method="LOCAL_ONLY",
        endpoint=None,
        location=str(path),
        dataset="ClinVar VCV XML",
    )
    return ResolvedResourceExecution(
        resource_id=resource_id,
        resource_version="2026-09",
        qualification_id=qualification_id,
        qualification_version="siraloom-resource-qualification-v1",
        contract=contract,
        contract_hash="a" * 64,
    )


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "ClinVarVCVRelease_2026-09.xml.gz"
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<ClinVarVariationRelease ReleaseDate="2026-09-03">
  <VariationArchive Accession="VCV000000001" Version="3" VariationID="12345">
    <ClassifiedRecord>
      <SimpleAllele ID="67890" VariationID="12345">
        <Location>
          <SequenceLocation Assembly="GRCh38" Chr="1" Accession="NC_000001.11"
              start="100" stop="100" positionVCF="100"
              referenceAllele="A" alternateAllele="G" />
        </Location>
      </SimpleAllele>
      <RCVList>
        <RCVAccession Accession="RCV000000001" Version="2" />
        <RCVAccession Accession="RCV000000002" Version="7" />
      </RCVList>
      <ClinicalAssertionList>
        <ClinicalAssertion>
          <ClinVarAccession Accession="SCV000000001" Version="4" />
          <Classification>
            <GermlineClassification>
              <Description>Pathogenic</Description>
              <ReviewStatus>criteria provided, single submitter</ReviewStatus>
            </GermlineClassification>
          </Classification>
          <AttributeSet>
            <Attribute Type="AssertionMethod">Example criteria</Attribute>
          </AttributeSet>
          <ObservedIn>
            <Condition>
              <Name>Example disease</Name>
            </Condition>
          </ObservedIn>
        </ClinicalAssertion>
        <ClinicalAssertion>
          <ClinVarAccession Accession="SCV000000002" Version="1" />
          <Classification>
            <GermlineClassification>
              <Description>Benign</Description>
              <ReviewStatus>criteria provided, single submitter</ReviewStatus>
            </GermlineClassification>
          </Classification>
          <ObservedIn>
            <Condition>
              <Name>Example disease</Name>
            </Condition>
          </ObservedIn>
        </ClinicalAssertion>
      </ClinicalAssertionList>
    </ClassifiedRecord>
  </VariationArchive>
</ClinVarVariationRelease>
"""
    with gzip.open(path, "wb") as handle:
        handle.write(xml.encode())
    return path


def test_clinvar_queries_all_submitted_assertions_and_release_identity(tmp_path):
    path = _write_fixture(tmp_path)
    provider = ClinVarVCVProvider.from_execution_contract(
        resolved=_resolved(path),
        resource_location=str(path),
        genome_build="GRCh38",
        index_root=str(path.parent / "cache"),
    )

    records = provider.query_variant(
        chromosome="chr1",
        position=100,
        reference="a",
        alternate="g",
    )

    assert {record.record_type for record in records} == {"SCV"}
    assert {(r.accession, r.version) for r in records} == {
        ("SCV000000001", "4"),
        ("SCV000000002", "1"),
    }
    assert records[0].payload["vcv"] == {
        "accession": "VCV000000001",
        "version": "3",
        "variation_id": "12345",
    }
    assert records[0].rcv_accessions == (
        "RCV000000001.2",
        "RCV000000002.7",
    )
    assert {r.classification for r in records} == {"Pathogenic", "Benign"}


def test_clinvar_index_is_invalidated_when_authoritative_release_changes(tmp_path):
    path = _write_fixture(tmp_path)
    provider = ClinVarVCVProvider.from_execution_contract(
        resolved=_resolved(path),
        resource_location=str(path),
        genome_build="GRCh38",
        index_root=str(path.parent / "cache"),
    )
    assert len(provider.query_variant(
        chromosome="1", position=100, reference="A", alternate="G"
    )) == 2

    with gzip.open(path, "wb") as handle:
        handle.write(
            b'<ClinVarVariationRelease><VariationArchive Accession="VCV000000009" '
            b'Version="1" VariationID="9"><ClassifiedRecord>'
            b'<SimpleAllele><Location><SequenceLocation Assembly="GRCh38" Chr="1" '
            b'start="200" stop="200" referenceAllele="C" alternateAllele="T"/>'
            b'</Location></SimpleAllele></ClassifiedRecord></VariationArchive>'
            b'</ClinVarVariationRelease>'
        )

    assert provider.query_variant(
        chromosome="1", position=100, reference="A", alternate="G"
    ) == []
    assert len(provider.query_variant(
        chromosome="1", position=200, reference="C", alternate="T"
    )) == 1


def test_clinvar_rejects_non_local_execution_contract(tmp_path):
    path = _write_fixture(tmp_path)
    resolved = _resolved(path)
    remote = ResourceExecutionContract(
        provider_id="NCBI ClinVar",
        provider_version="release-xml-v1",
        access_method="HTTPS",
        endpoint="https://example.invalid/clinvar.xml.gz",
        location=None,
        dataset="ClinVar VCV XML",
    )
    resolved = ResolvedResourceExecution(
        resource_id=resolved.resource_id,
        resource_version=resolved.resource_version,
        qualification_id=resolved.qualification_id,
        qualification_version=resolved.qualification_version,
        contract=remote,
        contract_hash=resolved.contract_hash,
    )
    try:
        ClinVarVCVProvider.from_execution_contract(
            resolved=resolved,
            resource_location=str(path),
            genome_build="GRCh38",
        )
    except ClinVarProviderError as exc:
        assert "LOCAL_ONLY" in str(exc)
    else:
        raise AssertionError("remote ClinVar execution contract must be rejected")


def test_clinvar_rejects_location_mismatch(tmp_path):
    path = _write_fixture(tmp_path)
    other = tmp_path / "ClinVarVCVRelease_2026-09-other.xml.gz"
    other.write_bytes(path.read_bytes())
    try:
        ClinVarVCVProvider.from_execution_contract(
            resolved=_resolved(path),
            resource_location=str(other),
            genome_build="GRCh38",
        )
    except ClinVarProviderError as exc:
        assert "location" in str(exc).lower()
    else:
        raise AssertionError("location mismatch must be rejected")
