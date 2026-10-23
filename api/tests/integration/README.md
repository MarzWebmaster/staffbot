# Integration tests

End-to-end checks for the security fixes (S-01 to S-06) and the managed
Hermes platform: packages/Alembic, LLM proxy, orchestrator, agent tools +
Hermes plugin, channel router, migration, and the portal in a real browser.

- Real: PostgreSQL, the FastAPI apps, HTTP between services, Chromium.
- Faked: Docker, the Hermes container, WhatsApp/Telegram managers, LLM providers.
  The real Hermes image and Docker behaviour must be verified on staging
  (see `docs/RUNBOOK_MANAGED_HERMES.md`).

Run: see the header of `run_all.sh`. Each suite wipes the test database.
