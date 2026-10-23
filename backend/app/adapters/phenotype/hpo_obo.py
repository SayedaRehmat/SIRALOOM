"""Local, version-pinned reader for the official HPO OBO release.

Only ``is_a`` edges are used for phenotype ancestry. HPO documents its terms as
a directed acyclic graph connected by ``is-a`` edges; other OBO relationships
are deliberately not treated as interchangeable phenotype subsumption.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from backend.app.domain.resource_source_contract import ResourceExecutionContract


class HPOOntologyError(ValueError):
    """The configured HPO artifact is invalid or does not match its pin."""


_TERM_ID = re.compile(r"^HP:\d{7}$")
_RELEASE = re.compile(
    r"(?:(?:hp/)?releases/)?(\d{4}-\d{2}-\d{2})(?:/hp(?:-base)?\.(?:obo|owl))?$"
)
_TERM_REFERENCE = re.compile(r"^(HP:\d{7})(?:\s+(.*))?$")
_RESOLVED_TERM_STATUSES = {"CURRENT", "ALTERNATE_ID", "OBSOLETE_REPLACED"}


@dataclass(frozen=True)
class HpoTerm:
    term_id: str
    label: str
    parents: tuple[str, ...]
    alternate_ids: tuple[str, ...]
    obsolete: bool
    replaced_by: tuple[str, ...]
    consider: tuple[str, ...]


@dataclass(frozen=True)
class HpoTermResolution:
    input_id: str
    status: str
    canonical_id: str | None = None
    label: str | None = None
    replacement_candidates: tuple[str, ...] = ()
    consider: tuple[str, ...] = ()
    ambiguous_candidates: tuple[str, ...] = ()


class HPOOboProvider:
    provider_id = "HPO"
    provider_version = "OBO"

    def __init__(
        self,
        path: str | Path,
        *,
        expected_sha256: str,
        expected_release: str,
    ) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise HPOOntologyError("Pinned HPO OBO file is unavailable")
        expected = str(expected_sha256 or "").strip().lower()
        if expected.startswith("sha256:"):
            expected = expected.partition(":")[2]
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise HPOOntologyError("A valid SHA-256 pin is required for the HPO OBO file")
        self.sha256 = self._sha256(self.path)
        if self.sha256 != expected:
            raise HPOOntologyError("HPO OBO checksum does not match the approved resource")
        self.terms, self.release = self._parse(self.path)
        release = _release_date(expected_release)
        if release != self.release:
            raise HPOOntologyError(
                f"HPO OBO release mismatch: resource pins {release}, file declares {self.release}"
            )
        self.aliases: dict[str, str] = {}
        alias_targets: dict[str, set[str]] = {}
        for term in self.terms.values():
            if len(term.alternate_ids) != len(set(term.alternate_ids)):
                raise HPOOntologyError(f"HPO term {term.term_id} repeats an alternate identifier")
            for alternate in term.alternate_ids:
                alias_targets.setdefault(alternate, set()).add(term.term_id)
        ambiguous_aliases: dict[str, tuple[str, ...]] = {}
        for alternate, targets in alias_targets.items():
            existing = self.terms.get(alternate)
            if existing is None and len(targets) == 1:
                self.aliases[alternate] = next(iter(targets))
                continue
            # An obsolete stanza and an alt_id on its single explicit
            # replacement are a common HPO representation. Direct resolution
            # uses the stanza's replaced_by while preserving obsolete status.
            if (
                existing is not None
                and existing.obsolete
                and len(existing.replaced_by) == 1
                and existing.replaced_by[0] in targets
                and targets == {existing.replaced_by[0]}
            ):
                continue
            candidates = set(targets)
            if existing is not None:
                candidates.add(existing.term_id)
            ambiguous_aliases[alternate] = tuple(sorted(candidates))
        self.ambiguous_aliases = ambiguous_aliases
        self._ancestor_cache: dict[str, frozenset[str]] = {}

    @classmethod
    def from_execution_contract(cls, contract: ResourceExecutionContract) -> HPOOboProvider:
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise HPOOntologyError("HPO OBO execution requires a qualified local file resource")
        toolchain = dict(contract.toolchain or {})
        checksum = toolchain.get("sha256") or toolchain.get("checksum")
        release = toolchain.get("release") or contract.dataset or contract.provider_version
        return cls(
            contract.location or "",
            expected_sha256=str(checksum or ""),
            expected_release=str(release or ""),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _parse(cls, path: Path) -> tuple[dict[str, HpoTerm], str]:
        terms: dict[str, HpoTerm] = {}
        header_release: str | None = None
        current: dict[str, object] | None = None

        def finish() -> None:
            nonlocal current
            if current is None:
                return
            term_id = str(current.get("id") or "")
            label = str(current.get("name") or "")
            if not _TERM_ID.fullmatch(term_id) or not label:
                raise HPOOntologyError("HPO OBO contains a term without a valid HP identifier or name")
            if term_id in terms:
                raise HPOOntologyError(f"HPO OBO contains duplicate term {term_id}")
            terms[term_id] = HpoTerm(
                term_id=term_id,
                label=label,
                parents=tuple(current.get("parents", ())),
                alternate_ids=tuple(current.get("alternate_ids", ())),
                obsolete=bool(current.get("obsolete", False)),
                replaced_by=tuple(current.get("replaced_by", ())),
                consider=tuple(current.get("consider", ())),
            )
            current = None

        with path.open("rt", encoding="utf-8") as stream:
            for raw_line in stream:
                line = raw_line.strip()
                if line.startswith("[") and line.endswith("]"):
                    finish()
                    if line == "[Term]":
                        current = {"parents": [], "alternate_ids": [], "replaced_by": [], "consider": []}
                    continue
                if not line or line.startswith("!"):
                    continue
                if current is None:
                    if line.startswith("data-version:"):
                        header_release = line.partition(":")[2].strip()
                    continue
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                value = value.strip().split(" ! ", 1)[0].strip()
                if key == "id" or key == "name":
                    if key in current:
                        raise HPOOntologyError(f"HPO OBO term repeats field {key}")
                    current[key] = value
                elif key == "is_a":
                    target = _term_reference(value)
                    if target is None:
                        raise HPOOntologyError(f"HPO OBO has invalid is_a target {value!r}")
                    current["parents"].append(target)
                elif key == "alt_id":
                    target = _term_reference(value)
                    if target is None:
                        raise HPOOntologyError(f"HPO OBO has invalid alt_id {value!r}")
                    current["alternate_ids"].append(target)
                elif key in {"replaced_by", "consider"}:
                    target = _term_reference(value)
                    if target is None:
                        raise HPOOntologyError(f"HPO OBO has invalid {key} target {value!r}")
                    current["replaced_by" if key == "replaced_by" else "consider"].append(target)
                elif key == "is_obsolete":
                    if value.lower() not in {"true", "false"}:
                        raise HPOOntologyError(
                            f"HPO OBO term {current.get('id', '<unknown>')} has invalid is_obsolete value"
                        )
                    if "obsolete" in current:
                        raise HPOOntologyError(
                            f"HPO OBO term {current.get('id', '<unknown>')} repeats field is_obsolete"
                        )
                    current["obsolete"] = value.lower() == "true"
        finish()
        if not terms:
            raise HPOOntologyError("HPO OBO contains no phenotype terms")
        if not header_release:
            raise HPOOntologyError("HPO OBO header has no data-version release")
        release = _release_date(header_release)
        for term in terms.values():
            for parent in term.parents:
                if parent not in terms:
                    raise HPOOntologyError(f"HPO term {term.term_id} has missing parent {parent}")
        # Keep only the active DFS path gray. A stack that eagerly marks all
        # pending siblings gray mistakes a converging DAG (diamond graph) for
        # a cycle when two branches share an ancestor.
        colors: dict[str, int] = {}
        for root, root_term in terms.items():
            if colors.get(root) == 2:
                continue
            colors[root] = 1
            stack: list[tuple[str, Iterator[str]]] = [(root, iter(root_term.parents))]
            while stack:
                term_id, parent_iterator = stack[-1]
                try:
                    parent = next(parent_iterator)
                except StopIteration:
                    colors[term_id] = 2
                    stack.pop()
                    continue
                color = colors.get(parent, 0)
                if color == 1:
                    raise HPOOntologyError(f"HPO OBO is_a graph contains a cycle at {parent}")
                if color == 0:
                    colors[parent] = 1
                    stack.append((parent, iter(terms[parent].parents)))
        return terms, release

    def resolve(self, value: str) -> HpoTermResolution:
        term_id = str(value or "").strip().upper()
        if not _TERM_ID.fullmatch(term_id):
            return HpoTermResolution(term_id, "INVALID")
        if term_id in self.ambiguous_aliases:
            return HpoTermResolution(
                term_id,
                "AMBIGUOUS",
                ambiguous_candidates=self.ambiguous_aliases[term_id],
            )
        term = self.terms.get(term_id)
        if term is not None and term.obsolete:
            replacement = self.terms.get(term.replaced_by[0]) if len(term.replaced_by) == 1 else None
            if replacement is not None and not replacement.obsolete:
                return HpoTermResolution(
                    term_id,
                    "OBSOLETE_REPLACED",
                    replacement.term_id,
                    replacement.label,
                    replacement_candidates=term.replaced_by,
                    consider=term.consider,
                )
            return HpoTermResolution(
                term_id,
                "OBSOLETE",
                replacement_candidates=term.replaced_by,
                consider=term.consider,
            )
        canonical = self.aliases.get(term_id, term_id)
        term = self.terms.get(canonical)
        if term is None:
            return HpoTermResolution(term_id, "UNKNOWN")
        return HpoTermResolution(term_id, "ALTERNATE_ID" if canonical != term_id else "CURRENT", canonical, term.label)

    def ancestors(self, value: str) -> frozenset[str]:
        resolution = self.resolve(value)
        if resolution.status not in _RESOLVED_TERM_STATUSES or not resolution.canonical_id:
            return frozenset()
        cached = self._ancestor_cache.get(resolution.canonical_id)
        if cached is not None:
            return cached
        found: set[str] = set()
        pending = list(self.terms[resolution.canonical_id].parents)
        while pending:
            term_id = pending.pop()
            if term_id in found:
                continue
            found.add(term_id)
            pending.extend(self.terms[term_id].parents)
        result = frozenset(found)
        self._ancestor_cache[resolution.canonical_id] = result
        return result

    def ancestor_map(self, terms: list[str] | tuple[str, ...]) -> dict[str, list[str]]:
        resolved: dict[str, list[str]] = {}
        for value in terms:
            result = self.resolve(value)
            if result.status in _RESOLVED_TERM_STATUSES and result.canonical_id:
                resolved[value] = sorted(self.ancestors(value))
        return resolved


def _release_date(value: str) -> str:
    match = _RELEASE.fullmatch(str(value or "").strip())
    if not match:
        raise HPOOntologyError(f"Invalid HPO release identity {value!r}")
    return match.group(1)


def _term_reference(value: str) -> str | None:
    """Return an HPO target ID, accepting OBO 1.2 trailing modifiers.

    OBO relationship lines permit ``{key=\"value\"}`` modifiers after the
    target identifier. The modifiers do not change the target used for this
    adapter's is-a graph, but malformed blocks must not be ignored.
    """
    match = _TERM_REFERENCE.fullmatch(value)
    if match is None:
        return None
    target, modifiers = match.groups()
    if modifiers is not None and not _is_balanced_modifier_block(modifiers):
        return None
    return target


def _is_balanced_modifier_block(value: str) -> bool:
    if not value.startswith("{") or not value.endswith("}"):
        return False
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quoted and char == "\\":
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "{":
            depth += 1
        elif not quoted and char == "}":
            depth -= 1
            if depth < 0 or (depth == 0 and index != len(value) - 1):
                return False
    return depth == 0 and not quoted and not escaped
