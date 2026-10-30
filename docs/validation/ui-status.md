# SIRALOOM Variant — UI Integration Validation

## Status

Implemented: core case, workspace, review, evidence-context and report pages are present in source.
Backend contract integration: automated tests cover selected API/client contracts; source inspection alone does not prove a deployed browser-to-database workflow.
Latest observed GitHub Actions run during this audit: frontend behavior tests PASS, Next.js production build PASS, production frontend container build PASS, Compose configuration validation PASS, and PostgreSQL/real Celery worker-loss integration PASS. The backend test suite PASS was also observed for commit `d3e50af39dee2c6c3c24c68f5e456be0d18148c6`; its backend image build was still running at the last check.
Historical local check: an earlier environment lacked installed Next.js/React dependencies, so a production build was not executed locally at that time.
Browser-level end-to-end validation against a deployed PostgreSQL + Redis + worker + API + frontend stack: NOT RUN in this audit.

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
