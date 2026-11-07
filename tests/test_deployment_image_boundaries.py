from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _compose(path: str) -> dict:
    with (ROOT / path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_development_api_and_beat_use_tool_neutral_image() -> None:
    services = _compose("docker-compose.yml")["services"]

    assert services["api"]["build"]["dockerfile"] == "docker/backend-api.Dockerfile"
    assert services["beat"]["build"]["dockerfile"] == "docker/backend-api.Dockerfile"
    assert services["worker"]["build"]["dockerfile"] == "docker/backend.Dockerfile"


def test_production_api_and_beat_are_separate_from_scientific_worker_images() -> None:
    services = _compose("docker-compose.production.yml")["services"]

    assert services["api"]["build"]["dockerfile"] == "docker/backend-api.Dockerfile"
    assert services["beat"]["build"]["dockerfile"] == "docker/backend-api.Dockerfile"
    assert services["worker"]["build"]["dockerfile"] == "docker/backend.Dockerfile"

    for service_name in ("api", "beat"):
        build_args = services[service_name]["build"].get("args", {})
        assert not any("BCFTOOLS" in str(key).upper() for key in build_args)
        assert not any("BCFTOOLS" in str(value).upper() for value in build_args)

    for service_name in (
        "worker-bcftools-1-24-1",
        "worker-bcftools-1-23-3",
        "worker-bcftools-1-22-3",
        "worker-bcftools-1-21-3",
    ):
        if service_name in services:
            assert (
                services[service_name]["build"]["dockerfile"]
                == "docker/backend-bcftools-source.Dockerfile"
            )


def test_api_image_contract_excludes_scientific_executables() -> None:
    dockerfile = (ROOT / "docker/backend-api.Dockerfile").read_text(encoding="utf-8")

    assert "COPY --from=bcftools" not in dockerfile
    assert "micromamba" not in dockerfile.lower()
    assert "&& ! command -v bcftools" in dockerfile
    assert 'CMD ["./scripts/start_api.sh"]' in dockerfile
