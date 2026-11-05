#!/usr/bin/env bash
set -euo pipefail

: "${BCFTOOLS_PROFILE_ID:?BCFTOOLS_PROFILE_ID is required}"
: "${BCFTOOLS_VERSION:?BCFTOOLS_VERSION is required}"
: "${HTSLIB_VERSION:?HTSLIB_VERSION is required}"
: "${BCFTOOLS_PROFILE_REGISTRY:?BCFTOOLS_PROFILE_REGISTRY is required}"

BCFTOOLS_PROFILE_REGISTRY="$(realpath "${BCFTOOLS_PROFILE_REGISTRY}")"
PREFIX="${BCFTOOLS_PREFIX:-/opt/conda}"
DESTDIR="${BCFTOOLS_DESTDIR:-}"
INSTALL_PREFIX="${DESTDIR}${PREFIX}"
WORKDIR="${BCFTOOLS_BUILD_DIR:-/tmp/bcftools-profile-build}"
mkdir -p "$WORKDIR" "$INSTALL_PREFIX"
cd "$WORKDIR"

trap 'status=$?; echo "BCFTOOLS_BUILD_FAILED profile=${BCFTOOLS_PROFILE_ID} line=${LINENO} status=${status} command=${BASH_COMMAND}" >&2; for binary in "${INSTALL_PREFIX:-}/bin/bcftools" "${INSTALL_PREFIX:-}/bin/bgzip"; do if [ -x "$binary" ]; then echo "--- ldd $binary ---" >&2; ldd "$binary" >&2 || true; fi; done; exit "$status"' ERR

# Read the exact profile record. The registry is the single source of truth
# for release versions, archive URLs and SHA-256 digests.
mapfile -t profile_fields < <(python - "$BCFTOOLS_PROFILE_REGISTRY" "$BCFTOOLS_PROFILE_ID" "$BCFTOOLS_VERSION" "$HTSLIB_VERSION" <<'PY'
import json, re, sys
path, profile_id, expected_bcftools, expected_htslib = sys.argv[1:]
payload = json.load(open(path, encoding="utf-8"))
matches = [p for p in payload.get("profiles", []) if p.get("id") == profile_id]
if len(matches) != 1:
    raise SystemExit(f"profile must resolve exactly once: {profile_id}")
p = matches[0]
if p.get("installation_method") != "verified_source_build":
    raise SystemExit(f"profile is not a verified source build: {profile_id}")
if p.get("bcftools_version") != expected_bcftools or p.get("htslib_version") != expected_htslib:
    raise SystemExit("requested versions do not match immutable profile record")
if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", expected_bcftools) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", expected_htslib):
    raise SystemExit("BCFtools and HTSlib versions must be explicit numeric release versions")
archives = {a.get("name"): a for a in p.get("source_archives", [])}
required = (f"htslib-{expected_htslib}.tar.bz2", f"bcftools-{expected_bcftools}.tar.bz2")
if set(archives) != set(required):
    raise SystemExit(f"source archive set must be exactly {required}")
for name in required:
    a = archives[name]
    url, digest = a.get("url"), a.get("sha256")
    if not isinstance(url, str) or not url.startswith("https://") or not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
        raise SystemExit(f"invalid pinned URL or SHA-256 for {name}")
    print(f"{name}\t{url}\t{digest}")
PY
)

if [ "${#profile_fields[@]}" -ne 2 ]; then
  echo "Expected exactly two pinned source archives for ${BCFTOOLS_PROFILE_ID}" >&2
  exit 1
fi

fetch_verified() {
  local name="$1" url="$2" digest="$3"
  curl --fail --location --retry 5 --retry-all-errors --connect-timeout 20 "$url" -o "$name"
  echo "$digest  $name" | sha256sum --check --status || {
    echo "SHA-256 mismatch for $name" >&2
    exit 1
  }
}

for record in "${profile_fields[@]}"; do
  IFS=$'\t' read -r name url digest <<< "$record"
  fetch_verified "$name" "$url" "$digest"
done

tar -xjf "htslib-${HTSLIB_VERSION}.tar.bz2"
tar -xjf "bcftools-${BCFTOOLS_VERSION}.tar.bz2"

export CFLAGS="${CFLAGS:--O2 -fPIC}"
export CPPFLAGS="${CPPFLAGS:-}"
export LDFLAGS="${LDFLAGS:-}"

install_with_destdir() {
  if [ -n "$DESTDIR" ]; then make install DESTDIR="$DESTDIR"; else make install; fi
}

(
  cd "htslib-${HTSLIB_VERSION}"
  ./configure --prefix="$PREFIX" --enable-libcurl --enable-plugins
  make -j"$(getconf _NPROCESSORS_ONLN)"
  install_with_destdir
)
(
  cd "bcftools-${BCFTOOLS_VERSION}"
  ./configure --prefix="$PREFIX" --with-htslib="$INSTALL_PREFIX"
  make -j"$(getconf _NPROCESSORS_ONLN)"
  install_with_destdir
)

export LD_LIBRARY_PATH="$INSTALL_PREFIX/lib:${CONDA_PREFIX:-/nonexistent}/lib:${LD_LIBRARY_PATH:-}"
test "$("$INSTALL_PREFIX/bin/bcftools" --version | sed -n '1p')" = "bcftools ${BCFTOOLS_VERSION}"
test "$("$INSTALL_PREFIX/bin/bcftools" --version | sed -n '2p')" = "Using htslib ${HTSLIB_VERSION}"
test "$("$INSTALL_PREFIX/bin/bgzip" --version | sed -n '1p')" = "bgzip (htslib) ${HTSLIB_VERSION}"

# Stage only non-system shared libraries needed by the runtime binaries.
if [ -n "${CONDA_PREFIX:-}" ] && [ "$INSTALL_PREFIX" != "$CONDA_PREFIX" ]; then
  mkdir -p "$INSTALL_PREFIX/lib"
  {
    for binary in "$INSTALL_PREFIX/bin/bcftools" "$INSTALL_PREFIX/bin/bgzip" "$INSTALL_PREFIX/bin/htsfile" "$INSTALL_PREFIX/bin/tabix" "$INSTALL_PREFIX/bin/annot-tsv" "$INSTALL_PREFIX/bin/ref-cache"; do
      if [ -x "$binary" ]; then
        ldd "$binary" | awk '{ for (i = 1; i <= NF; i++) if (substr($i, 1, 1) == "/") { print $i; break } }'
      fi
    done
  } | sort -u | while IFS= read -r library; do
    case "$library" in
      "$CONDA_PREFIX"/lib/*)
        target="$INSTALL_PREFIX/lib/$(basename "$library")"
        if [ ! -e "$target" ]; then cp -L "$library" "$target"; fi
        ;;
    esac
  done
fi

"$INSTALL_PREFIX/bin/bcftools" --version
