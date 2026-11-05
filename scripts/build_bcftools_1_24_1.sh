#!/usr/bin/env bash
set -euo pipefail

# Keep native-toolchain image failures diagnosable in CI. The failing command
# and dynamic-loader state are emitted before the shell exits.
trap 'status=$?; echo "BCFTOOLS_BUILD_FAILED line=${LINENO} status=${status} command=${BASH_COMMAND}" >&2; if [ -x "${INSTALL_PREFIX:-}/bin/bcftools" ]; then echo "--- bcftools ldd ---" >&2; ldd "${INSTALL_PREFIX}/bin/bcftools" >&2 || true; fi; if [ -x "${INSTALL_PREFIX:-}/bin/bgzip" ]; then echo "--- bgzip ldd ---" >&2; ldd "${INSTALL_PREFIX}/bin/bgzip" >&2 || true; fi; exit "${status}"' ERR

# PREFIX is the final runtime path compiled into BCFtools (not the temporary
# build path). DESTDIR stages installation without changing embedded paths.
PREFIX="${BCFTOOLS_PREFIX:-/opt/conda}"
DESTDIR="${BCFTOOLS_DESTDIR:-}"
INSTALL_PREFIX="${DESTDIR}${PREFIX}"
WORKDIR="${BCFTOOLS_BUILD_DIR:-/tmp/bcftools-1.24.1-build}"
mkdir -p "$WORKDIR" "$INSTALL_PREFIX"
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

install_with_destdir() {
  if [ -n "$DESTDIR" ]; then
    make install DESTDIR="$DESTDIR"
  else
    make install
  fi
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
  install_with_destdir
)

(
  cd bcftools-1.24.1
  ./configure --prefix="$PREFIX" --with-htslib="$INSTALL_PREFIX"
  make -j"$(getconf _NPROCESSORS_ONLN)"
  install_with_destdir
)

# The installed binaries are staged under DESTDIR, but their compiled-in
# plugin path remains the final PREFIX path used in the runtime image.
export LD_LIBRARY_PATH="$INSTALL_PREFIX/lib:${CONDA_PREFIX:-/nonexistent}/lib:${LD_LIBRARY_PATH:-}"
test "$("$INSTALL_PREFIX/bin/bcftools" --version | sed -n '1p')" = "bcftools 1.24.1"
test "$("$INSTALL_PREFIX/bin/bcftools" --version | sed -n '2p')" = "Using htslib 1.24.1"
test "$("$INSTALL_PREFIX/bin/bgzip" --version | sed -n '1p')" = "bgzip (htslib) 1.24.1"

# Copy only non-system shared libraries required by the installed tools and
# plugins. Compiler binaries, headers and build metadata remain in the build
# stage. When PREFIX is the Conda environment itself, no copy is needed.
if [ -n "${CONDA_PREFIX:-}" ] && [ "$INSTALL_PREFIX" != "$CONDA_PREFIX" ]; then
  mkdir -p "$INSTALL_PREFIX/lib"
  {
    find "$INSTALL_PREFIX/bin" -maxdepth 1 -type f -executable -print
    find "$INSTALL_PREFIX/libexec/bcftools" -maxdepth 1 -type f -name '*.so' -print 2>/dev/null || true
  } | while IFS= read -r binary; do
    ldd "$binary" 2>/dev/null | awk '/=> \// {print $3} /^\// {print $1}'
  done | sort -u | while IFS= read -r library; do
    case "$library" in
      "$CONDA_PREFIX"/lib/*)
        target="$INSTALL_PREFIX/lib/$(basename "$library")"
        if [ ! -e "$target" ]; then
          cp -L "$library" "$target"
        fi
        ;;
    esac
  done
fi

"$INSTALL_PREFIX/bin/bcftools" --version
