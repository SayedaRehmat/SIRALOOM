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
| `container_image` | Immutable image digest reported by the Kubernetes API for the running container whose ID matches the worker's cgroup |

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

## Non-Kubernetes installations

Docker Compose, bare-metal, and other non-Kubernetes workers currently cannot provide the required trusted image identity through this provider. Clinical execution therefore fails closed on those installations. Do not work around this by setting an image-digest environment variable.

A separate host/container-runtime attestor is required for those deployment modes. It must obtain the running container identity and immutable image digest from the trusted host runtime, bind that identity to the worker process, and provide authenticated evidence whose trust anchor is controlled outside the worker container. This provider is not implemented yet.

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
