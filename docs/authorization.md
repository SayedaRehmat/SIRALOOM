# Authorization matrix

All active organization roles can read cases, specimens, analyses, variants, evidence, audit history, and reports within their organization. No role can read another organization's case-derived resource.

| Role | Case/specimen/artifact write, analysis start | Review actions | Report create | Clinical report finalization | Membership administration |
| --- | --- | --- | --- | --- | --- |
| platform_admin | yes | yes | yes | yes | yes |
| organization_admin | yes | yes | yes | yes | yes |
| lab_director | yes | yes | yes | yes | no |
| clinical_geneticist | yes | yes | yes | yes | no |
| reviewer | no | yes | no | no | no |
| bioinformatician | yes | no | yes | no | no |
| lab_scientist | yes | no | yes | no | no |
| read_only | no | no | no | no | no |

The backend resolves a Firebase subject to an active database membership before authorizing a request. The frontend may hide controls but is not an authorization boundary.
