"""ClinVar archived-release discovery adapter.

ClinVar has distinct weekly and monthly release semantics. SIRALOOM uses the
monthly archived release as the reproducible resource identity; weekly feeds
are synchronization feeds and are not silently treated as immutable releases.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

CLINVAR_XML_INDEX = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/xml/"
MONTHLY_FILE_RE = re.compile(
    r'href="(ClinVarVCVRelease_[^"]+\.xml\.gz)"', re.IGNORECASE
)


class ClinVarReleaseProvider:
    """Discover the latest archived ClinVar VCV XML release."""

    name = "ClinVar"
    index_url = CLINVAR_XML_INDEX

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
        url = self.index_url + filename
        return [{
            "name": "ClinVar VCV XML",
            "provider": self.name,
            "resource_type": "EVIDENCE",
            "version": filename,
            "genome_build": None,
            "access_method": "NCBI_FTP_HTTPS",
            "location": url,
            "checksum": None,
            "metadata": {
                "release_channel": "MONTHLY_ARCHIVED",
                "release_identity": filename,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                "source_index": self.index_url,
                "integrity_status": "SOURCE_CHECKSUM_NOT_PUBLISHED_BY_ADAPTER",
                "requires_checksum_qualification": True,
            },
        }]
