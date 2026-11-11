# Clinical worker runtime attestation

## Purpose and safety boundary

A clinical assay-validation approval must identify the exact software and execution environment that was validated. A version label, queue name, lock-file reference, or environment variable is not proof of the bytes executing in a worker.

Before a clinical analysis can execute or resume, SIRALOOM measures and compares these six required components against the immutable assay-validation snapshot:

| Component key | Runtime evidence |
|---|---|
| `bcftools` | SHA-256 of the resolved executable plus the version reported by that executable |
| `htslib` | SHA-256 of the unique HTSlib shared library linked to the BCFtools executable plus its reported version |
| `native_toolchain_lock` | SHA-256 of the registered platform-specific native toolchain lock |
| `python_dependency_lock` | SHA-256 of the deployed `uv.lock` |
| `siraloom_variant_workflow` | Deterministic SHA-256 of Python source files under `backend/app/workflows`, plus the persisted workflow version |
| `container_image` | Kubernetes immutable image ID, or a signed host-broker identity bound to the connecting host PID and its process/container cgroup; Docker identity includes the image config digest and ordered rootfs layer digests, while bare metal uses a root-managed release-manifest digest |

A missing, extra, duplicated, malformed, or changed component blocks clinical execution. The same gate runs before interrupted-workflow recovery on redelivery and retry. The workflow and report sign-out paths also require a persisted successful runtime-attestation event.

## Kubernetes requirements

The initial trusted image-identity provider supports Kubernetes workers. It does not trust `SIRALOOM_RUNTIME_IMAGE_DIGEST` or another deployment-supplied digest variable.

Configure these downward-API environment variables on the worker container:

```yaml
env:
  - name: POD_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: POD_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  - name: SIRALOOM_K8S_CONTAINER_NAME
    value: siraloom-worker
```

The worker's service account must have a namespace-scoped `get` permission for Pod objects. Run clinical workers in a dedicated namespace so the read permission does not expose unrelated workloads.

Example least-privilege namespace role and binding (replace the service-account name if the deployment uses another one):

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: siraloom-worker
  namespace: siraloom-clinical
automountServiceAccountToken: true
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: siraloom-worker-runtime-attestation
  namespace: siraloom-clinical
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: siraloom-worker-runtime-attestation
  namespace: siraloom-clinical
subjects:
  - kind: ServiceAccount
    name: siraloom-worker
    namespace: siraloom-clinical
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: siraloom-worker-runtime-attestation
```

The worker uses the in-cluster API service address, projected service-account token, and mounted CA certificate. It requires the Pod status to identify exactly one running container matching the current worker's 64-character cgroup container ID and requires an immutable `sha256` image digest in `status.containerStatuses[].imageID`.

## Docker Compose and bare-metal host attestor

Non-Kubernetes deployments can use the host-side broker in `scripts/host_runtime_attestor.py`. The broker runs outside the worker, authenticates the connecting process with Linux Unix-socket peer credentials, reads host `/proc` process/cgroup identity, obtains Docker image metadata through the host Docker Engine, and signs a fresh challenge-bound response with an Ed25519 private key. The worker verifies that signature with a pinned public key. The Docker socket and signing private key are never mounted into the worker.

The host private key is a separate trust anchor: generate it on the host, keep it root-owned and mode 0600, and mount only the public key read-only into the worker. The public key must be pinned in the trusted worker image or supplied as a root-owned, read-only host mount; do not let an untrusted worker environment replace the trust anchor.

Example key creation on the host:

```bash
sudo install -d -m 0700 /etc/siraloom/attestor
sudo openssl genpkey -algorithm ED25519 -out /etc/siraloom/attestor/private.pem
sudo chmod 0600 /etc/siraloom/attestor/private.pem
sudo openssl pkey -in /etc/siraloom/attestor/private.pem -pubout -out /etc/siraloom/attestor/public.pem
sudo chmod 0644 /etc/siraloom/attestor/public.pem
```

Run the broker as a host service with access to the Docker CLI/Engine:

```bash
sudo python scripts/host_runtime_attestor.py \
  --socket /run/siraloom/host-attestor.sock \
  --private-key /etc/siraloom/attestor/private.pem \
  --mode docker
```

For Docker Compose, bind-mount only the broker socket and public key into the designated clinical worker, preferably read-only for the public key. Configure `HOST_RUNTIME_ATTESTOR_SOCKET=/run/siraloom/host-attestor.sock` and `HOST_RUNTIME_ATTESTOR_PUBLIC_KEY=/etc/siraloom/attestor/public.pem`. Do not mount `/var/run/docker.sock` into the worker. Restrict the host socket's group and mount exposure to the clinical worker service; any process that can access that socket can request a signature for its own host PID.

The broker binds the host PID obtained from `SO_PEERCRED` to its current process start time and cgroup. In Docker mode it resolves the exact container from host cgroup metadata, verifies the Docker Engine container ID, obtains the immutable image config ID and ordered rootfs layer digests, and hashes that complete identity tuple. A mutable tag is never accepted as image identity.

For bare metal, run the same broker with `--mode bare-metal`, `--install-root` and `--release-manifest`. The worker process must run with its working directory inside the configured installation root. The installation tree and release manifest must be root-owned and not writable by the worker account. The manifest is JSON with `schema_version: "1"` and a non-empty `files` array; each entry contains a root-relative `path` and lowercase SHA-256 `sha256`. The broker rejects traversal, symlinks, missing files, writable/non-root-owned files, and any digest mismatch, then signs the release-manifest digest together with the connecting process identity. Generate the inventory during deployment, not from worker-controlled input. This mode identifies a controlled software release rather than a container image.

The host broker requires a root-owned Ed25519 private key and OpenSSL. Use `--socket-gid` to assign the socket to a dedicated host group, then grant that group only to the intended clinical worker container/process. The worker requires OpenSSL with Ed25519 support for signature verification. The host broker requires Linux `SO_PEERCRED`, host `/proc` visibility, and Docker CLI access in Docker mode. Unsupported cgroup layouts, inaccessible process metadata, missing image layers, stale challenges, unavailable keys, or invalid signatures fail closed. Do not use `SIRALOOM_RUNTIME_IMAGE_DIGEST` or any other environment-provided digest as proof.

Kubernetes remains supported and is used when no host-attestor socket is configured. If a host-attestor socket is configured, failure of that broker does not fall back to Kubernetes or an environment value.

## Capture the measured manifest

Run the following command inside the exact worker container/pod that the laboratory intends to validate:

```bash
python scripts/print_runtime_component_manifest.py --workflow-version 2.1
```

The command prints the six measured component identities and a canonical manifest digest. Retain that output as controlled validation evidence and submit the six component entries in the assay-validation record. Do not copy example/test digests into a clinical submission. Repeat measurement for each distinct worker image/profile used by the assay.

## Laboratory validation manifest

An assay-validation submission must declare exactly the six component keys above. The laboratory's approved validation evidence must contain the actual expected SHA-256 values for the deployed image and every component. Example hashes in automated tests are synthetic and are not clinical validation evidence.

A deployment change that alters any measured component requires the laboratory to assess the change under its approved change-control procedure and, where required, perform re-verification or revalidation and approve a new assay-validation revision before clinical use.

## Provenance and limitations

A successful execution appends a `CLINICAL_RUNTIME_ATTESTED` event to SIRALOOM's hash-linked audit event chain, including the component manifest and its canonical manifest digest. A failed check appends `CLINICAL_RUNTIME_ATTESTATION_BLOCKED` and blocks the analysis. Workflow resumption and clinical report sign-out require the successful event to match the immutable assay-validation snapshot.

This is a software execution-integrity control. It does not establish analytical performance, clinical validity, regulatory clearance, accreditation, or laboratory competence. The laboratory remains responsible for validating its intended-use method, maintaining controlled procedures, approving changes, and authorizing clinical release.
