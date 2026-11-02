from backend.app.infrastructure.resource_providers import normalization_releases


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _release(tag, *, prerelease=False, draft=False):
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "tarball_url": f"https://api.github.com/repos/test/project/tarball/{tag}",
        "html_url": f"https://github.com/test/project/releases/tag/{tag}",
        "published_at": "2026-10-01T00:00:00Z",
    }


def test_bcftools_provider_discovers_historical_and_current_stable_releases(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse([
            _release("1.24"),
            _release("1.23.2"),
            _release("1.25-rc1", prerelease=True),
            _release("1.22", draft=True),
        ])

    monkeypatch.setattr(normalization_releases.httpx, "get", fake_get)

    candidates = normalization_releases.BCFtoolsReleaseProvider().discover()

    assert [item["version"] for item in candidates] == ["1.24", "1.23.2"]
    assert all(item["resource_type"] == "NORMALIZATION" for item in candidates)
    assert all(item["source_contract"]["publisher"] == "Samtools" for item in candidates)
    assert all(item["source_contract"]["checksum_status"] == "UNKNOWN" for item in candidates)
    assert all(item["source_contract"]["license_status"] == "REVIEW_REQUIRED" for item in candidates)
    assert candidates[0]["metadata"]["execution"]["toolchain"]["bcftools"]["version"] == "1.24"
    assert candidates[0]["metadata"]["execution"]["toolchain"]["bcftools"]["executable"] == "bcftools"
    assert calls[0][0] == "https://api.github.com/repos/samtools/bcftools/releases"
    assert calls[0][1]["params"] == {"per_page": 100, "page": 1}


def test_gatk_provider_discovers_release_tags_without_claiming_execution_support(monkeypatch):
    monkeypatch.setattr(
        normalization_releases.httpx,
        "get",
        lambda *_args, **_kwargs: FakeResponse([
            _release("4.6.0.0"),
            _release("v4.7.0.0"),
            _release("4.8.0.0-beta", prerelease=True),
        ]),
    )

    candidates = normalization_releases.GATKReleaseProvider().discover()

    assert [item["version"] for item in candidates] == ["4.6.0.0", "4.7.0.0"]
    assert all(item["provider"] == "GATK" for item in candidates)
    assert all(item["resource_type"] == "NORMALIZATION" for item in candidates)
    assert candidates[1]["metadata"]["execution"]["toolchain"]["gatk"]["version"] == "4.7.0.0"
    assert candidates[1]["metadata"]["execution"]["toolchain"]["gatk"]["executable"] == "gatk"
    assert "LeftAlignAndTrimVariants" in candidates[1]["metadata"]["official_documentation_url"]


def test_release_discovery_paginates_when_official_endpoint_has_full_page(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs["params"]["page"])
        if kwargs["params"]["page"] == 1:
            return FakeResponse([_release(f"1.{index}") for index in range(100)])
        return FakeResponse([])

    monkeypatch.setattr(normalization_releases.httpx, "get", fake_get)

    candidates = normalization_releases.BCFtoolsReleaseProvider().discover()

    assert len(candidates) == 100
    assert calls == [1, 2]
