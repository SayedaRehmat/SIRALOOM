from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.app.domain import gene_disease_resource_acquisition as acquisition
from backend.app.domain import resource_qualification


G2P_CSV = (
    "G2P ID,Gene symbol,HGNC ID,Disease name,Disease MONDO,Allelic requirement,"
    "Molecular mechanism,Confidence,Publication,Publication phenotypes,"
    "Cross cutting modifier,Publication variant types,"
    "Evidence based variant consequence,Publication molecular mechanism evidence\n"
    "G2P001,GENE1,HGNC:1,Example disorder,MONDO:0000001,biallelic_autosomal,"
    "loss of function,definitive,PMID:1,HP:0001250,,,,\n"
).encode()

CLINGEN_CSV = (
    "CLINGEN GENE VALIDITY CURATIONS\n"
    "FILE CREATED: 2026-11-10\n"
    "GENE SYMBOL,GENE ID (HGNC),DISEASE LABEL,DISEASE ID (MONDO),SOP,CLASSIFICATION,"
    "ONLINE REPORT,CLASSIFICATION DATE,GCEP,MOI\n"
    "GENE1,HGNC:1,Example disorder,MONDO:0000001,SOP10,Definitive,"
    "https://search.clinicalgenome.org/kb/gene-validity/example,2026-11-10,Expert Panel,AR\n"
).encode()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_acquisition_preserves_exact_source_bytes_and_manifest(tmp_path, monkeypatch):
    payloads = {
        acquisition.G2P_URL: G2P_CSV,
        acquisition.CLINGEN_URL: CLINGEN_CSV,
    }

    def fake_download(url, destination):
        data = payloads[url]
        destination.write_bytes(data)
        return url, len(data), hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(acquisition, "_download_atomic", fake_download)
    manifest = acquisition.acquire_gene_disease_snapshots(tmp_path / "acquired")
    root = tmp_path / "acquired"

    assert (root / "G2P_all.csv").read_bytes() == G2P_CSV
    assert (root / "ClinGen_gene_validity.csv").read_bytes() == CLINGEN_CSV
    assert manifest["schema"] == "siraloom.gene-disease-acquisition.v1"
    assert len(manifest["artifacts"]) == 2
    g2p, clingen = manifest["artifacts"]
    assert g2p["release_identity_kind"] == "ACQUISITION_DATE_UTC_ON_THE_FLY_EXPORT"
    assert g2p["sha256"] == hashlib.sha256(G2P_CSV).hexdigest()
    assert clingen["release_identity"] == "2026-11-10"
    assert clingen["release_identity_kind"] == "PUBLISHER_FILE_CREATED_DATE"
    assert clingen["sha256"] == hashlib.sha256(CLINGEN_CSV).hexdigest()
    saved = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest


def test_acquisition_refuses_to_overwrite_existing_release_directory(tmp_path):
    root = tmp_path / "existing"
    root.mkdir()
    (root / "G2P_all.csv").write_bytes(b"preserve")
    with pytest.raises(acquisition.GeneDiseaseAcquisitionError, match="new or empty"):
        acquisition.acquire_gene_disease_snapshots(root)
    assert (root / "G2P_all.csv").read_bytes() == b"preserve"


def test_clingen_release_identity_requires_publisher_file_created_date(tmp_path):
    path = tmp_path / "clingen.csv"
    path.write_text("CLINGEN GENE VALIDITY CURATIONS\nGENE SYMBOL,GENE ID (HGNC)\n", encoding="utf-8")
    with pytest.raises(acquisition.GeneDiseaseAcquisitionError, match="FILE CREATED"):
        acquisition._clingen_file_created(path)


@pytest.mark.parametrize(
    ("provider", "filename", "release", "payload", "source_url", "final_url"),
    [
        (
            "Gene2Phenotype", "G2P_all.csv", "2026-11-10", G2P_CSV,
            acquisition.G2P_URL, acquisition.G2P_URL,
        ),
        (
            "ClinGen Gene-Disease Validity", "ClinGen_gene_validity.csv", "2026-11-10", CLINGEN_CSV,
            acquisition.CLINGEN_URL, acquisition.CLINGEN_URL,
        ),
    ],
)
def test_provider_qualification_uses_real_production_parser_and_pinned_manifest(
    tmp_path, provider, filename, release, payload, source_url, final_url
):
    artifact = tmp_path / filename
    artifact.write_bytes(payload)
    digest = _sha(artifact)
    manifest = {
        "schema": "siraloom.gene-disease-acquisition.v1",
        "acquired_at_utc": "2026-11-10T00:00:00+00:00",
        "artifacts": [{
            "provider": provider,
            "filename": filename,
            "release_identity": release,
            "sha256": digest,
            "size_bytes": artifact.stat().st_size,
            "requested_url": source_url,
            "final_url": final_url,
            "release_identity_kind": "PUBLISHER_FILE_CREATED_DATE" if provider.startswith("ClinGen") else "ACQUISITION_DATE_UTC_ON_THE_FLY_EXPORT",
        }],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    manifest_sha = _sha(manifest_path)
    resource = type("Resource", (), {
        "provider": provider,
        "version": release,
        "checksum": digest,
        "metadata_json": {
            "execution": {"toolchain": {
                "release": release,
                "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_sha,
            }},
            "acquisition_manifest_path": str(manifest_path),
            "acquisition_manifest_sha256": manifest_sha,
            "source_requested_url": source_url,
            "source_final_url": final_url,
        },
    })()
    blockers = []
    checks = {}
    resource_qualification._qualify_gene_disease_provider(resource, artifact, blockers, checks)
    assert blockers == []
    assert checks["gene_disease_acquisition_manifest"]["status"] == "VERIFIED"
    assert checks["gene_disease_source"]["status"] == "PROVIDER_PARSER_QUALIFIED"
    assert checks["gene_disease_source"]["record_count"] == 1
    assert checks["gene_disease_source"]["sha256"] == digest


def test_provider_qualification_blocks_manifest_tampering(tmp_path):
    artifact = tmp_path / "g2p.csv"
    artifact.write_bytes(G2P_CSV)
    digest = _sha(artifact)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"schema":"tampered"}', encoding="utf-8")
    resource = type("Resource", (), {
        "provider": "Gene2Phenotype",
        "version": "2026-11-10",
        "checksum": digest,
        "metadata_json": {
            "execution": {"toolchain": {
                "release": "2026-11-10",
                "manifest_path": str(manifest_path),
                "manifest_sha256": "0" * 64,
            }},
            "source_requested_url": acquisition.G2P_URL,
            "source_final_url": acquisition.G2P_URL,
        },
    })()
    blockers = []
    checks = {}
    resource_qualification._qualify_gene_disease_provider(resource, artifact, blockers, checks)
    assert "GENE_DISEASE_ACQUISITION_MANIFEST_DIGEST_MISMATCH" in blockers
    assert "gene_disease_source" not in checks


def test_official_reconciliation_qualification_script_is_syntax_valid():
    script = Path(__file__).resolve().parents[1] / "scripts" / "qualify_official_gene_disease_sources.py"
    source = script.read_text(encoding="utf-8")
    compile(source, str(script), "exec")


def test_download_rejects_unapproved_redirect_and_preserves_no_partial_file(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://attacker.invalid/payload.csv"

        def read(self, _size):
            return b"payload"

    monkeypatch.setattr(acquisition, "urlopen", lambda *_args, **_kwargs: Response())
    destination = tmp_path / "source.csv"
    with pytest.raises(acquisition.GeneDiseaseAcquisitionError, match="unapproved endpoint"):
        acquisition._download_atomic(acquisition.G2P_URL, destination)
    assert not destination.exists()


def test_download_enforces_maximum_source_size(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "MAX_SOURCE_BYTES", 10)

    class Response:
        def __init__(self):
            self.remaining = 11

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return acquisition.G2P_URL

        def read(self, size):
            if self.remaining <= 0:
                return b""
            amount = min(size, self.remaining)
            self.remaining -= amount
            return b"x" * amount

    monkeypatch.setattr(acquisition, "urlopen", lambda *_args, **_kwargs: Response())
    destination = tmp_path / "oversized.csv"
    with pytest.raises(acquisition.GeneDiseaseAcquisitionError, match="exceeds"):
        acquisition._download_atomic(acquisition.G2P_URL, destination)
    assert not destination.exists()
