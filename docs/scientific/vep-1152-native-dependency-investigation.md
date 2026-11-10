# VEP 115.2 native dependency investigation

## Evidence source

GitHub Actions run [42585935794](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/42585935794), commit `bf4830abc689c5746985df1769a3b8202e6bbbeb`, executed on native `ubuntu-24.04` x86_64 and `ubuntu-24.04-arm` aarch64 runners. The diagnostic artifacts are:

- `vep-cpan-build-diagnostics-x86_64` (artifact 13659599760)
- `vep-cpan-build-diagnostics-aarch64` (artifact 13659309526)

Both Perl 5.38.5 builds passed. The combined Carton resolution failed on both architectures because the two Bio modules below could not configure/build. Offline reinstall and lock generation were skipped.

## Findings by dependency

### DBD::mysql 4.050 — native compile succeeded on both architectures

The CPAN logs show `mysql_config` was found and returned MariaDB include paths and the architecture-specific MariaDB client library path:

- x86_64: `/usr/include/mariadb`, `/usr/lib/x86_64-linux-gnu`
- aarch64: `/usr/include/mariadb`, `/usr/lib/aarch64-linux-gnu`

Both logs report `Successfully installed DBD-mysql-4.050`. This is a compile/install result, not yet a runtime connection qualification. The optional database capability still needs module-load and configured MariaDB connection tests before it can be declared supported.

### Bio::DB::HTS 3.01 — HTSlib discovery failed on both architectures

The module's Build.PL reports its documented search order: explicit `--htslib`, `HTSLIB_DIR`, `--prefix`, Alien::HTSlib, pkg-config, then common locations. It returned `N/A` and did not generate MYMETA, so the failure is at configure/discovery, before native compilation.

The workflow installs `libhts-dev`, but the build did not discover that installation. The next experiment must inspect the actual installed headers, shared/static libraries and pkg-config metadata on each runner, then pass an explicit verified HTSlib prefix (or build a separately checksum-pinned HTSlib source tree). Do not invoke VEP's installer path that clones its mutable default HTSlib version.

### Bio::DB::BigFile 1.07 — UCSC Kent source was not configured

The build log explicitly asks for the compiled `jkweb.a` library and a `KENT_SRC` path. No Kent source tree was supplied. Compilation then fails with:

```text
fatal error: common.h: No such file or directory
```

This is a missing UCSC Kent include/source configuration, not evidence of an architecture incompatibility. Before enabling the capability, pin a Kent source release/archive checksum, build its required libraries natively on both architectures, set `KENT_SRC`, and run real BigWig/BigBed query fixtures.

## Profile separation change

The core VEP runtime cpanfile no longer treats these three optional/native capabilities as mandatory dependencies. Three independent capability inputs now exist:

- `vep-115.2-capability-mysql.cpanfile`
- `vep-115.2-capability-hts.cpanfile`
- `vep-115.2-capability-bigfile.cpanfile`

This is a dependency-boundary correction, not capability qualification. Each optional capability remains unqualified until its own architecture-specific source/build lock, runtime tests and evidence are committed.

## Offline reproduction

The lock workflow now blocks outbound IPv4 and IPv6 traffic before the cached deployment reinstall. This is intended to make network isolation an enforced test condition rather than relying on Carton's `--cached` flag alone. The gate remains pending until both architecture jobs complete the isolated reinstall and produce their candidate locks.

## Qualification status

VEP remains `CANDIDATE`. No OCI image, cache, plugin, annotation-fixture or production-routing qualification is implied by these dependency findings.
