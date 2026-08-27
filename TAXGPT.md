# TaxGPT backend

TaxGPT is an additive bounded context inside the existing Pestcontrol Flask service. It shares the service process and PostgreSQL connection but owns only `/api/taxgpt/*` routes, the `taxgpt_session` cookie, and `taxgpt_*` tables. It does not modify Paces, voice, Greptile, Anglera, or legacy authentication contracts.

## Production deployment

1. Back up the database, then apply the idempotent migration:

   ```sh
   psql "$SQLALCHEMY_DATABASE_URI" -v ON_ERROR_STOP=1 -f app/taxgpt/migrations/001_create_taxgpt_tables.sql
   ```

2. Configure the shared service:

   - `APP_ENV=production`
   - `SECRET_KEY`: a long, randomly generated secret shared by every web worker
   - `SQLALCHEMY_DATABASE_URI`: the existing PostgreSQL connection
   - `FRONTEND_ORIGINS`: comma-separated exact frontend origins, including the TaxGPT frontend
   - `AUTO_CREATE_TABLES=false` and `TAXGPT_AUTO_CREATE_TABLES=false`: production schema changes must go through reviewed migrations
   - `TAXGPT_COOKIE_SECURE=true`: required behind HTTPS
   - `TAXGPT_TRUST_PROXY_HEADERS=true` only when requests arrive through a trusted proxy that replaces `X-Forwarded-For`
   - `OPENAI_API_KEY`: optional; without it the application returns deterministic local responses
   - `OPENAI_MODEL`: defaults to `gpt-4.1-mini`

   Optional bounds and defaults are documented in `.env.example`.

3. Deploy the existing `Procfile`. No second service or worker is required. Verify:

   ```sh
   curl -fsS https://your-api.example.com/api/taxgpt/health
   ```

4. Point the frontend's server-side `TAXGPT_API_URL` at the shared API origin. Browser requests should continue to use `/api/taxgpt/*` through the frontend proxy so the HttpOnly session cookie remains same-origin.

## Operational properties

- Passwords use Werkzeug's adaptive password hashing; session tokens are random, stored only as SHA-256 hashes, HttpOnly, SameSite Strict, scoped to the host, and revocable.
- Authentication and demo abuse limits are stored in PostgreSQL, so they work across Gunicorn workers. Put a WAF or load-balancer rate limit in front as an additional perimeter control.
- Every authenticated query is scoped by TaxGPT workspace. Files are size/type/signature checked, stored privately in PostgreSQL, and downloaded only through authenticated workspace checks.
- Request bodies, file sizes, PDF page counts, generated-input sizes, OpenAI timeouts, and retries are bounded. TaxGPT responses use no-store, clickjacking, MIME-sniffing, referrer, and permissions headers.
- The application removes stale rate events and old expired/revoked sessions during startup. Database backups, retention, encryption at rest, monitoring, alerting, and secret rotation remain deployment responsibilities.
- AI tax output must be presented as assistive research, not a substitute for licensed professional review. Citation links and conclusions should be verified before filing or client delivery.

## Verification

Run the bounded-context tests and the complete shared regression suite before deployment:

```sh
python -m unittest tests.test_taxgpt_api -v
python -m unittest discover -s tests -v
pip check
```

The migration can be reapplied safely: it uses `CREATE TABLE IF NOT EXISTS` and creates only `taxgpt_*` objects.
