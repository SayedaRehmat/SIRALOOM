#!/usr/bin/env bash
set -euo pipefail

PREFIX="${BCFTOOLS_PREFIX:-/opt/conda}"
WORKDIR="${BCFTOOLS_BUILD_DIR:-/tmp/bcftools-1.24.1-build}"
mkdir -p "$WORKDIR" "$PREFIX"
cd "$WORKDIR"

fetch_verified() {
  local name="$1" sha256="$2"
  local url="https://downloads.sourceforge.net/project/samtools/samtools/1.24.1/$name"
  curl --fail --location --retry 5 --retry-all-errors --connect-timeout 20 "$url" -o "$name"
  echo "$sha256  $name" | sha256sum --check --status || {
    echo "SHA-256 mismatch for $name" >&2
    exit 1
  }
}

fetch_verified htslib-1.24.1.tar.bz2 0fa28b8a5395b3ce489d24c79697d81ceb93534907e17b92bb8a5306bebcdeb5
fetch_verified bcftools-1.24.1.tar.bz2 02ccf63e5f478a1374ae6dbcb7cfde9840a96ddf5167fd88f5d47b78f5906a5a

tar -xjf htslib-1.24.1.tar.bz2
tar -xjf bcftools-1.24.1.tar.bz2

export CFLAGS="${CFLAGS:--O2 -fPIC}"
export CPPFLAGS="${CPPFLAGS:-}"
export LDFLAGS="${LDFLAGS:-}"

(
  cd htslib-1.24.1
  ./configure --prefix="$PREFIX" --enable-libcurl --enable-plugins
  make -j"$(getconf _NPROCESSORS_ONLN)"
  make install
)

(
  cd bcftools-1.24.1
  ./configure --prefix="$PREFIX" --with-htslib="$PREFIX"
  make -j"$(getconf _NPROCESSORS_ONLN)"
  make install
)

test "$("$PREFIX/bin/bcftools" --version | sed -n '1p')" = "bcftools 1.24.1"
test "$("$PREFIX/bin/bcftools" --version | sed -n '2p')" = "Using htslib 1.24.1"
test "$("$PREFIX/bin/bgzip" --version | sed -n '1p')" = "bgzip (htslib) 1.24.1"
"$PREFIX/bin/bcftools" --version
