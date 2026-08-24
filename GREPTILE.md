# Greptile API in LifeManagerBackend

Greptile is registered in the existing `app:create_app()` service and reuses
the deployment's current `SQLALCHEMY_DATABASE_URI`, `SECRET_KEY`,
`FRONTEND_ORIGINS`, and Gunicorn entry point. No additional environment
variable or service is required.

At application startup, only the namespaced `greptile_*` tables are created
with `checkfirst` semantics. Existing Paces, pest-control, CRM, and voice-agent
tables are not altered. The demo Greptile account is seeded idempotently as
`a@gmail.com` with password `1`.

The frontend should continue using its existing `NEXT_PUBLIC_API_URL` or
`NEXT_PUBLIC_PACES_API_URL`. Next.js proxies `/api/greptile/*` through that
same backend origin so the opaque HttpOnly session cookie remains first-party.

Run the focused regression suite with:

```bash
.venv/bin/python -m unittest tests.test_greptile_api tests.test_paces_demo_api -v
```
