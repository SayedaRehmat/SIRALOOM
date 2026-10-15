"""Convert local filesystem paths and file URIs without losing platform syntax."""

from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname


def local_path_from_uri(value: str) -> Path | None:
    """Resolve a local path or local file URI; reject non-local URI schemes."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    if len(raw_value) >= 3 and raw_value[1] == ":" and raw_value[2] in {"/", "\\"}:
        return Path(raw_value).expanduser().resolve(strict=False)
    parsed = urlparse(raw_value)
    if not parsed.scheme:
        return Path(raw_value).expanduser().resolve(strict=False)
    if parsed.scheme.lower() != "file" or parsed.netloc.lower() not in {"", "localhost"}:
        return None
    if not parsed.path:
        return None
    return Path(url2pathname(parsed.path)).expanduser().resolve(strict=False)
