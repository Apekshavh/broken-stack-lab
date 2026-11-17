# Broken Stack Lab

A reproducible troubleshooting lab: a small multi-service stack, a one-command fault injector, and an automated verifier that decides whether the stack is *actually* fixed.

```
client -> Nginx (:8080) -> Flask/gunicorn -> PostgreSQL
                                          -> Redis (cache)
```

Everything runs in Docker Compose. The verifier uses only the Python standard library, so there is nothing to install besides Docker and Python 3.

## Quick start

```bash
docker compose up -d --build
docker compose ps                  # all services running; postgres, redis, app healthy
python3 verify.py                  # healthy baseline: all checks pass
```

Manual smoke test:

```bash
curl -s localhost:8080/health
curl -s -X POST localhost:8080/notes -H 'Content-Type: application/json' -d '{"text":"hello"}'
curl -s localhost:8080/notes       # "source": "db"
curl -s localhost:8080/notes       # "source": "cache" (within 30s)
```

Reset to the healthy baseline at any time: `./reset.sh`. Full teardown including data: `docker compose down -v`.

## The application

A tiny notes API:

| Endpoint | Behavior |
|---|---|
| `POST /notes` | Inserts a note into PostgreSQL and invalidates the Redis cache |
| `GET /notes` | Returns notes from Redis if cached (30s TTL), otherwise from PostgreSQL |
| `GET /health` | 200 only if both PostgreSQL and Redis respond, otherwise 503 |

If Redis fails, the app logs the error and falls back to PostgreSQL. That means a Redis problem causes a *partial* failure rather than a total outage, which is what makes the scenarios below non-obvious.

## Scenarios

| Scenario | Inject | Area |
|---|---|---|
| `redis-auth` | `./scenarios/redis-auth/inject.sh` | Service configuration, authentication, healthchecks |

### Try it yourself

```bash
./scenarios/redis-auth/inject.sh   # break the stack
python3 verify.py                  # fails while broken
# investigate and fix, then:
python3 verify.py                  # passes only when genuinely fixed
./reset.sh                         # restore the baseline
```

The fault is written to a temporary file at injection time, so nothing in the repo reveals it. Investigate using `docker compose ps`, `docker compose logs`, `docker compose exec`, and `docker inspect`.

### Walkthrough: redis-auth (spoilers)

<details>
<summary>Symptoms, investigation, root cause, and fix</summary>

**Symptoms**
- `GET /health` returns 503 with `"redis": "down"`.
- Writing and listing notes still works, because the app falls back to PostgreSQL, but every read is served from `db` and never from `cache`.
- `docker compose exec redis redis-cli ping` returns `NOAUTH Authentication required`.

**Investigation**
1. `curl /health` shows the failure is Redis-specific, not PostgreSQL or Nginx.
2. `docker compose logs app` shows repeated Redis authentication errors on cache reads and writes.
3. `docker compose exec redis redis-cli ping` confirms Redis is reachable but rejects unauthenticated clients, so this is an auth problem, not a network or crash problem.
4. `docker inspect <redis container>` and `docker compose exec redis ps aux` show Redis is running with `--requirepass`, which the baseline `docker-compose.yml` does not set.

**Root cause**
Redis was restarted with a password (as in a credential rotation), but neither the application nor the Redis healthcheck was given the new credential.

**Fix** (see the `solution/redis-auth` branch)
- Store the password in `.env` (git-ignored; `.env.example` is committed) rather than hardcoding it.
- Pass it to the app as `REDIS_PASSWORD` and use it in the Redis client in `app/app.py`.
- Start Redis with `--requirepass ${REDIS_PASSWORD}` and update its healthcheck to authenticate. Without that change the healthcheck never passes and dependent services never start.

**Trade-offs**
- Passing the password on the command line exposes it via `docker inspect` and `ps`. Acceptable for a lab; in production use Docker/Kubernetes secrets or a mounted config file.
- Removing the password would also "fix" the symptom, but only if the rotation was unintended. Keeping authentication is the safer assumption.

</details>

## How the verifier works

`verify.py` exits 0 only if every check passes:

1. `/health` returns 200 with both PostgreSQL and Redis `ok`.
2. `POST /notes` creates a note (201).
3. `GET /notes` returns the newly created note.
4. A second `GET /notes` is served from `cache`.
5. The note survives a PostgreSQL restart (skip with `--quick`).
6. The app logs contain no dependency errors since verification began.

Check 4 matters because it closes a shortcut: loosening the health check would turn `/health` green, but only a working Redis cache can pass the cache check. Check 6 catches failures that stay hidden behind the fallback path.

## Repo layout

```
docker-compose.yml
app/                         Flask app, Dockerfile, requirements
nginx/nginx.conf
db/init.sql                  schema, applied on first Postgres start
scenarios/redis-auth/        fault injector
reset.sh                     restore the healthy baseline
verify.py                    automated pass/fail verifier
```

## Requirements

Docker with Compose v2 (`docker compose`) and Python 3.8+. 
