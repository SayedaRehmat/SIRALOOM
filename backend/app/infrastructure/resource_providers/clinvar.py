"""ClinVar archived-release discovery adapter.

ClinVar has distinct weekly and monthly release semantics. SIRALOOM uses the
monthly archived release as the reproducible resource identity; weekly feeds
are synchronization feeds and are not silently treated as immutable releases.
"""

from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import httpx

CLINVAR_XML_INDEX = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/xml/"
MONTHLY_FILE_RE = re.compile(
    r'href="(ClinVarVCVRelease_\d{4}-\d{2}\.xml\.gz)"', re.IGNORECASE
)


class ClinVarReleaseProvider:
    """Discover the latest archived ClinVar VCV XML release."""

    name = "ClinVar"
    index_url = CLINVAR_XML_INDEX

    def stage(self, descriptor: dict[str, object], destination: Path) -> dict[str, object]:
        """Stream the exact discovered release and return its transport digest.

        The digest is computed from the bytes received by SIRALOOM. It is not
        presented as an NCBI-published checksum. Production qualification must
        additionally establish source-integrity evidence before activation.
        """
        location = descriptor.get("location")
        if not isinstance(location, str) or not location.startswith(self.index_url):
            raise ValueError("ClinVar staging requires an official NCBI ClinVar URL")

        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256()
        size = 0
        with httpx.stream("GET", location, timeout=120.0, follow_redirects=True) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)

        return {
            "source": location,
            "local_path": str(destination),
            "sha256": digest.hexdigest(),
            "size_bytes": size,
            "metadata": {
                "integrity": "TRANSPORT_DIGEST_ONLY",
                "source_checksum_verified": False,
                "release_identity": descriptor.get("version"),
            },
        }

    def discover(self) -> list[dict[str, Any]]:
        response = httpx.get(self.index_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()

        matches = MONTHLY_FILE_RE.findall(response.text)
        if not matches:
            raise RuntimeError("ClinVar XML index contained no VCV release files")

        # The NCBI index exposes release files in directory order. Do not infer
        # a semantic database version from the filename; retain the exact URL
        # and filename as the resource identity.
        filename = sorted(set(matches))[-1]
        release = filename.removeprefix("ClinVarVCVRelease_").removesuffix(".xml.gz")
        url = self.index_url + filename
        return [{
            "name": "ClinVar VCV XML",
            "provider": self.name,
            "resource_type": "EVIDENCE",
            "version": release,
            "genome_build": None,
            "access_method": "NCBI_FTP_HTTPS",
            "location": url,
            "checksum": None,
            "source_contract": {
                "publisher": "NCBI ClinVar",
                "canonical_source_url": "https://www.ncbi.nlm.nih.gov/clinvar/",
                "artifact_url": url,
                "release_identity": filename,
                "access_mode": "PUBLIC",
                "license_status": "REVIEW_REQUIRED",
                "license_url": None,
                "terms_url": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
                "checksum_status": "NOT_PUBLISHED",
                "authority_evidence_url": "https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/",
            },
            "metadata": {
                "release_channel": "MONTHLY_ARCHIVED",
                "release_identity": filename,
                "release_month": release,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                "source_index": self.index_url,
                "integrity_status": "SOURCE_CHECKSUM_NOT_PUBLISHED_BY_ADAPTER",
                "requires_checksum_qualification": True,
            },
        }]
