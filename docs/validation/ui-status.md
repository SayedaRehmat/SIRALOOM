# SIRALOOM Variant — UI Integration Validation

## Status

Implemented: yes
Backend contract integration: verified against the existing Phase 1 API routes
Python backend tests: 57/57 PASS
TypeScript syntax/type-check: PASS using a temporary dependency stub because the environment has no installed Next.js/React packages
Next.js production build: NOT EXECUTED — dependency installation timed out in the current environment

## Implemented user flow

1. Create/load a case
2. Select VCF
3. Register the input artifact
4. Start a durable analysis
5. Poll persisted analysis state
6. Reconnect after browser refresh using stored case/analysis IDs
7. View workflow step state
8. View variants
9. Inspect population/evidence records
10. Start human review
11. Accept/reject ACMG criterion proposals
12. Request more evidence
13. Approve classification
14. Generate report
15. Finalize report
16. Open report artifact
17. Export full case history
18. Poll export state
19. Download case-history ZIP

## Reliability properties

- The browser does not execute long-running scientific work.
- Analysis status is persisted server-side.
- UI polling is observational only.
- A browser disconnect does not cancel the analysis.
- Case and analysis IDs are preserved in browser local storage for development reconnection.
- Export status is persisted and separately polled.
- Large VCF uploads are written in chunks rather than loaded fully into memory by the artifact store.

## Security/clinical boundary

The current UI uses the existing development identity endpoints and is not a production authentication/RBAC implementation. It must not be presented as production clinical security validation.

## Next validation gate

Run the full Docker Compose stack in a controlled environment with pinned frontend dependencies and execute a browser-level end-to-end test against PostgreSQL + Redis + worker + API + frontend.
