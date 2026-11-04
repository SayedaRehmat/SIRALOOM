"""Official release discovery for normalization engines.

Release discovery is intentionally metadata-only. It creates CANDIDATE
resources; it does not download, install, qualify, approve, or activate a
release. The resource lifecycle performs integrity/runtime qualification, and
each laboratory separately approves a qualified release before execution.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import httpx


_GITHUB_API = "https://api.github.com/repos"
_USER_AGENT = "SIRALOOM-scientific-resource-discovery/1.0"
_RELEASE_PAGES = 10
_RELEASES_PER_PAGE = 100


def _stable_releases(repository: str) -> Iterable[dict[str, Any]]:
    """Yield stable GitHub releases without assuming a current/latest version."""
    for page in range(1, _RELEASE_PAGES + 1):
        response = httpx.get(
            f"{_GITHUB_API}/{repository}/releases",
            params={"per_page": _RELEASES_PER_PAGE, "page": page},
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": _USER_AGENT,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Official release endpoint for {repository} returned a non-list payload")
        for release in payload:
            if isinstance(release, dict) and not release.get("draft") and not release.get("prerelease"):
                yield release
        if len(payload) < _RELEASES_PER_PAGE:
            break


def _candidate(
    *,
    repository: str,
    provider: str,
    version: str,
    tag: str,
    release: dict[str, Any],
    documentation_url: str,
    toolchain_key: str,
) -> dict[str, Any]:
    artifact_url = str(
        release.get("tarball_url")
        or f"{_GITHUB_API}/{repository}/tarball/{tag}"
    )
    release_url = str(release.get("html_url") or f"https://github.com/{repository}/releases/tag/{tag}")
    return {
        "name": provider,
        "provider": provider,
        "resource_type": "NORMALIZATION",
        "version": version,
        "genome_build": None,
        "access_method": "HTTPS",
        "location": None,
        "checksum": None,
        "population_definition": None,
        "metadata": {
            "capabilities": ["NORMALIZATION"],
            "release_tag": tag,
            "release_notes_url": release_url,
            "published_at": release.get("published_at"),
            "official_documentation_url": documentation_url,
            "discovery_scope": "OFFICIAL_STABLE_GITHUB_RELEASE",
            "qualification_required": True,
            "activation_policy": "LAB_APPROVAL_REQUIRED",
            "execution": {
                "provider_id": provider,
                "provider_version": version,
                "access_method": "HTTPS",
                "endpoint": artifact_url,
                "dataset": f"{provider} source release {tag}",
                "toolchain": {
                    toolchain_key: {
                        "version": version,
                        "executable": toolchain_key,
                    }
                },
            },
        },
        "source_contract": {
            "publisher": "Samtools" if toolchain_key == "bcftools" else "Broad Institute",
            "canonical_source_url": f"https://github.com/{repository}",
            "artifact_url": artifact_url,
            "release_identity": tag,
            "access_mode": "PUBLIC",
            # Licensing and source checksums are not inferred from a GitHub
            # release tag. Qualification remains blocked pending evidence.
            "license_status": "REVIEW_REQUIRED",
            "checksum_status": "UNKNOWN",
            "authority_evidence_url": documentation_url,
        },
    }


class BCFtoolsReleaseProvider:
    """Discover all published stable BCFtools releases from the official repo."""

    repository = "samtools/bcftools"
    documentation_url = "https://samtools.github.io/bcftools/bcftools.html"

    def discover(self) -> list[dict[str, Any]]:
        candidates = []
        for release in _stable_releases(self.repository):
            tag = str(release.get("tag_name") or "").strip()
            version = tag.removeprefix("v")
            if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
                continue
            candidates.append(_candidate(
                repository=self.repository,
                provider="bcftools",
                version=version,
                tag=tag,
                release=release,
                documentation_url=self.documentation_url,
                toolchain_key="bcftools",
            ))
        return candidates


class GATKReleaseProvider:
    """Discover published stable GATK releases without claiming adapter support."""

    repository = "broadinstitute/gatk"
    documentation_url = (
        "https://gatk.broadinstitute.org/hc/en-us/articles/"
        "21905044109467-LeftAlignAndTrimVariants"
    )

    def discover(self) -> list[dict[str, Any]]:
        candidates = []
        for release in _stable_releases(self.repository):
            tag = str(release.get("tag_name") or "").strip()
            version = tag.removeprefix("v")
            if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
                continue
            candidates.append(_candidate(
                repository=self.repository,
                provider="GATK",
                version=version,
                tag=tag,
                release=release,
                documentation_url=self.documentation_url,
                toolchain_key="gatk",
            ))
        return candidates
