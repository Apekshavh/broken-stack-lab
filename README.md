# Broken Stack Lab (healthy baseline)

Stack: Nginx -> Flask (gunicorn) -> PostgreSQL + Redis, all in Docker Compose.

## Run
    docker compose up -d --build
    docker compose ps

## Smoke test
    curl -s localhost:8080/health
    curl -s -X POST localhost:8080/notes -H 'Content-Type: application/json' -d '{"text":"hello"}'
    curl -s localhost:8080/notes     # source: db
    curl -s localhost:8080/notes     # source: cache

## Persistence check
    docker compose restart postgres && curl -s localhost:8080/notes

## Reset
    docker compose down -v

## Scenario: redis-auth
    ./scenarios/redis-auth/inject.sh   # break the stack
    python3 verify.py                  # should FAIL while broken
    # ...investigate and fix...
    python3 verify.py                  # should PASS once genuinely fixed
    ./reset.sh                         # restore the healthy baseline

`python3 verify.py --quick` skips the Postgres restart check.
