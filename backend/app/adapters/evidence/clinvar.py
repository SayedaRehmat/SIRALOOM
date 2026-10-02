from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.app.domain.resource_execution import ResolvedResourceExecution


class ClinVarProviderError(RuntimeError):
    """Raised when a governed ClinVar release cannot be queried safely."""


@dataclass(frozen=True)
class ClinVarAssertion:
    record_type: str
    accession: str
    version: str | None
    variation_id: str | None
    rcv_accessions: tuple[str, ...]
    genome_build: str
    chromosome: str
    position: int
    reference: str
    alternate: str
    classification: str | None
    review_status: str | None
    condition: str | None
    submitter: str | None
    assertion_method: str | None
    record_sha256: str
    payload: dict[str, Any]


class ClinVarVCVProvider:
    """Query a pinned NCBI ClinVar VCV XML release through a local derived index.

    The XML release is the authoritative resource. SQLite is only a deterministic
    query acceleration layer and is rebuilt whenever the source checksum changes.
    The adapter never queries a rolling/current ClinVar API.
    """

    provider_id = "NCBI ClinVar"
    provider_version = "release-xml-v1"
    dataset = "ClinVar VCV XML"

    def __init__(
        self,
        *,
        xml_path: str,
        resource_id: UUID,
        resource_version: str,
        qualification_id: UUID,
        qualification_version: str,
        contract_hash: str,
        genome_build: str,
        index_root: str,
    ) -> None:
        self.xml_path = Path(xml_path)
        self.resource_id = resource_id
        self.resource_version = resource_version
        self.qualification_id = qualification_id
        self.qualification_version = qualification_version
        self.contract_hash = contract_hash
        self.genome_build = genome_build
        self.index_path = (\n            Path(index_root)\n            / "clinvar"\n            / str(resource_id)\n            / resource_version\n            / genome_build\n            / "index.sqlite3"\n        )
        self._validate_inputs()

    @classmethod
    def from_execution_contract(
        cls,
        *,
        resolved: ResolvedResourceExecution,
        resource_location: str | None,
        genome_build: str,
        index_root: str,
    ) -> "ClinVarVCVProvider":
        contract = resolved.contract
        if contract.provider_id != cls.provider_id:
            raise ClinVarProviderError(
                f"ClinVar provider mismatch: {contract.provider_id!r}"
            )
        if contract.provider_version != cls.provider_version:
            raise ClinVarProviderError(
                f"ClinVar provider version mismatch: {contract.provider_version!r}"
            )
        if contract.access_method != "LOCAL_ONLY":
            raise ClinVarProviderError(
                "ClinVar VCV execution must use LOCAL_ONLY for the staged authoritative XML artifact."
            )
        if not contract.location:
            raise ClinVarProviderError("ClinVar execution contract has no local artifact location.")
        if resource_location is None or os.path.abspath(resource_location) != os.path.abspath(contract.location):
            raise ClinVarProviderError(
                "ClinVar execution location does not match the registered resource location."
            )
        return cls(
            xml_path=contract.location,
            resource_id=resolved.resource_id,
            resource_version=resolved.resource_version,
            qualification_id=resolved.qualification_id,
            qualification_version=resolved.qualification_version,
            contract_hash=resolved.contract_hash,
            genome_build=genome_build,
            index_root=index_root,
        )

    def query_variant(
        self,
        *,
        chromosome: str,
        position: int,
        reference: str,
        alternate: str,
    ) -> list[ClinVarAssertion]:
        self._ensure_index()
        key = _variant_key(self.genome_build, chromosome, position, reference, alternate)
        with sqlite3.connect(self.index_path) as connection:
            rows = connection.execute(
                """
                SELECT record_type, accession, version, variation_id, rcv_accessions,
                       genome_build, chromosome, position, reference, alternate,
                       classification, review_status, condition, submitter,
                       assertion_method, record_sha256, payload_json
                FROM clinvar_records
                WHERE variant_key = ?
                ORDER BY record_type, accession, COALESCE(version, '')
                """,
                (key,),
            ).fetchall()
        return [_row_to_assertion(row) for row in rows]

    def execution_metadata(self) -> dict[str, Any]:
        source_sha256 = _sha256_file(self.xml_path)
        index_sha256 = _sha256_file(self.index_path) if self.index_path.exists() else None
        return {
            "authoritative_artifact": str(self.xml_path),
            "authoritative_artifact_sha256": source_sha256,
            "derived_index": str(self.index_path),
            "derived_index_sha256": index_sha256,
            "index_schema_version": "1",
            "resource_id": str(self.resource_id),
            "resource_version": self.resource_version,
            "qualification_id": str(self.qualification_id),
            "qualification_version": self.qualification_version,
            "contract_hash": self.contract_hash,
        }

    def _validate_inputs(self) -> None:
        if not self.xml_path.is_file():
            raise ClinVarProviderError(f"ClinVar XML artifact does not exist: {self.xml_path}")
        if not self.xml_path.name.startswith("ClinVarVCVRelease_") or not self.xml_path.name.endswith(".xml.gz"):
            raise ClinVarProviderError(
                f"Unexpected ClinVar VCV artifact filename: {self.xml_path.name}"
            )
        if self.genome_build not in {"GRCh37", "GRCh38"}:
            raise ClinVarProviderError(f"Unsupported ClinVar genome build: {self.genome_build}")

    def _ensure_index(self) -> None:
        source_sha256 = _sha256_file(self.xml_path)
        if _index_is_current(self.index_path, source_sha256, self.resource_version, self.genome_build):
            return
        _build_index(
            xml_path=self.xml_path,
            index_path=self.index_path,
            source_sha256=source_sha256,
            resource_version=self.resource_version,
            genome_build=self.genome_build,
        )


def _variant_key(
    genome_build: str,
    chromosome: str,
    position: int,
    reference: str,
    alternate: str,
) -> str:
    return "|".join(
        (
            genome_build,
            chromosome.removeprefix("chr"),
            str(position),
            reference.upper(),
            alternate.upper(),
        )
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _index_is_current(
    index_path: Path,
    source_sha256: str,
    resource_version: str,
    genome_build: str,
) -> bool:
    if not index_path.is_file():
        return False
    try:
        with sqlite3.connect(index_path) as connection:
            rows = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
        return (
            rows.get("schema_version") == "1"
            and rows.get("source_sha256") == source_sha256
            and rows.get("resource_version") == resource_version
            and rows.get("genome_build") == genome_build
        )
    except (sqlite3.Error, OSError):
        return False


def _build_index(
    *,
    xml_path: Path,
    index_path: Path,
    source_sha256: str,
    resource_version: str,
    genome_build: str,
) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{index_path.name}.",
        suffix=".tmp",
        dir=index_path.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with sqlite3.connect(temporary_path) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE clinvar_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    variant_key TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    accession TEXT NOT NULL,
                    version TEXT,
                    variation_id TEXT,
                    rcv_accessions TEXT NOT NULL,
                    genome_build TEXT NOT NULL,
                    chromosome TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    reference TEXT NOT NULL,
                    alternate TEXT NOT NULL,
                    classification TEXT,
                    review_status TEXT,
                    condition TEXT,
                    submitter TEXT,
                    assertion_method TEXT,
                    record_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX idx_clinvar_variant_key
                    ON clinvar_records(variant_key);

                CREATE INDEX idx_clinvar_accession
                    ON clinvar_records(record_type, accession, version);
                """
            )
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                (
                    ("schema_version", "1"),
                    ("source_sha256", source_sha256),
                    ("resource_version", resource_version),
                    ("genome_build", genome_build),
                ),
            )

            with gzip.open(xml_path, "rb") as handle:
                for event, element in ET.iterparse(handle, events=("end",)):
                    if _local_name(element.tag) != "VariationArchive":
                        continue
                    for row in _rows_from_variation_archive(element, genome_build):
                        connection.execute(
                            """
                            INSERT INTO clinvar_records (
                                variant_key, record_type, accession, version,
                                variation_id, rcv_accessions, genome_build,
                                chromosome, position, reference, alternate,
                                classification, review_status, condition,
                                submitter, assertion_method, record_sha256,
                                payload_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            row,
                        )
                    element.clear()
            connection.commit()
        os.replace(temporary_path, index_path)
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        raise ClinVarProviderError(f"Failed to build ClinVar derived index: {exc}") from exc


def _rows_from_variation_archive(
    element: ET.Element,
    genome_build: str,
) -> list[tuple[Any, ...]]:
    variation_id = element.attrib.get("VariationID")
    vcv_accession = element.attrib.get("Accession")
    vcv_version = element.attrib.get("Version")
    if not vcv_accession:
        return []

    locations = [
        node
        for node in element.iter()
        if _local_name(node.tag) == "SequenceLocation"
        and node.attrib.get("Assembly") == genome_build
        and all(
            node.attrib.get(key)
            for key in ("Chr", "start", "referenceAllele", "alternateAllele")
        )
    ]
    if not locations:
        return []

    rcv_accessions = _rcv_accessions(element)
    assertions = [
        node for node in element.iter()
        if _local_name(node.tag) == "ClinicalAssertion"
    ]
    if not assertions:
        assertions = [None]

    rows: list[tuple[Any, ...]] = []
    for location in locations:
        chromosome = str(location.attrib["Chr"])
        position = int(location.attrib.get("positionVCF") or location.attrib["start"])
        reference = str(
            location.attrib.get("referenceAlleleVCF")
            or location.attrib["referenceAllele"]
        )
        alternate = str(
            location.attrib.get("alternateAlleleVCF")
            or location.attrib["alternateAllele"]
        )
        for assertion in assertions:
            classification = _text_at(assertion, "Classification/GermlineClassification/Description") if assertion is not None else None
            review_status = _text_at(assertion, "Classification/GermlineClassification/ReviewStatus") if assertion is not None else None
            condition = _first_descendant_text(
                assertion,
                {"Trait", "Condition"},
            ) if assertion is not None else None
            submitter = _first_descendant_text(
                assertion,
                {"SubmitterName", "Submitter", "Organization"},
            ) if assertion is not None else None
            assertion_method = _attribute_value(
                assertion,
                element_name="Attribute",
                attribute_name="Type",
                attribute_value="AssertionMethod",
            ) if assertion is not None else None
            if assertion is not None:
                accession_node = next(
                    (
                        node for node in assertion.iter()
                        if _local_name(node.tag) == "ClinVarAccession"
                    ),
                    None,
                )
                scv_accession = accession_node.attrib.get("Accession") if accession_node is not None else None
                scv_version = accession_node.attrib.get("Version") if accession_node is not None else None
            else:
                scv_accession = None
                scv_version = None

            payload = {
                "vcv": {
                    "accession": vcv_accession,
                    "version": vcv_version,
                    "variation_id": variation_id,
                },
                "scv": (
                    {
                        "accession": scv_accession,
                        "version": scv_version,
                    }
                    if scv_accession
                    else None
                ),
                "rcv_accessions": list(rcv_accessions),
                "genome_build": genome_build,
                "location": dict(location.attrib),
                "classification": classification,
                "review_status": review_status,
                "condition": condition,
                "submitter": submitter,
                "assertion_method": assertion_method,
            }
            record_type = "SCV" if scv_accession else "VCV"
            accession = scv_accession or vcv_accession
            version = scv_version or vcv_version
            record_xml = ET.tostring(assertion or element, encoding="utf-8")
            rows.append(
                (
                    _variant_key(genome_build, chromosome, position, reference, alternate),
                    record_type,
                    accession,
                    version,
                    variation_id,
                    json.dumps(rcv_accessions, separators=(",", ":")),
                    genome_build,
                    chromosome,
                    position,
                    reference,
                    alternate,
                    classification,
                    review_status,
                    condition,
                    submitter,
                    assertion_method,
                    hashlib.sha256(record_xml).hexdigest(),
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                )
            )
    return rows


def _rcv_accessions(element: ET.Element) -> tuple[str, ...]:
    values: list[str] = []
    for node in element.iter():
        if _local_name(node.tag) not in {"RCVAccession", "ClinVarAccession"}:
            continue
        accession = node.attrib.get("Accession") or node.attrib.get("Acc")
        if accession and accession.startswith("RCV"):
            version = node.attrib.get("Version")
            values.append(f"{accession}.{version}" if version else accession)
    return tuple(dict.fromkeys(values))


def _text_at(element: ET.Element | None, path: str) -> str | None:
    if element is None:
        return None
    current: ET.Element | None = element
    for part in path.split("/"):
        if not part:
            continue
        current = next(
            (
                child for child in current
                if _local_name(child.tag) == part
            ),
            None,
        )
        if current is None:
            return None
    return _normalize_text(current.text if current is not None else None)


def _first_descendant_text(
    element: ET.Element | None,
    names: set[str],
) -> str | None:
    if element is None:
        return None
    for node in element.iter():
        if _local_name(node.tag) not in names:
            continue
        text = _normalize_text(node.text)
        if text:
            return text
        for child in node:
            child_text = _normalize_text(child.text)
            if child_text:
                return child_text
    return None


def _attribute_value(
    element: ET.Element | None,
    *,
    element_name: str,
    attribute_name: str,
    attribute_value: str,
) -> str | None:
    if element is None:
        return None
    for node in element.iter():
        if (
            _local_name(node.tag) == element_name
            and node.attrib.get(attribute_name) == attribute_value
        ):
            return _normalize_text(node.text)
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def _row_to_assertion(row: tuple[Any, ...]) -> ClinVarAssertion:
    (
        record_type,
        accession,
        version,
        variation_id,
        rcv_json,
        genome_build,
        chromosome,
        position,
        reference,
        alternate,
        classification,
        review_status,
        condition,
        submitter,
        assertion_method,
        record_sha256,
        payload_json,
    ) = row
    return ClinVarAssertion(
        record_type=record_type,
        accession=accession,
        version=version,
        variation_id=variation_id,
        rcv_accessions=tuple(json.loads(rcv_json or "[]")),
        genome_build=genome_build,
        chromosome=chromosome,
        position=int(position),
        reference=reference,
        alternate=alternate,
        classification=classification,
        review_status=review_status,
        condition=condition,
        submitter=submitter,
        assertion_method=assertion_method,
        record_sha256=record_sha256,
        payload=json.loads(payload_json),
    )
