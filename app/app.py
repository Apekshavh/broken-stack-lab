import json
import logging
import os

import psycopg2
import redis
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = app.logger

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "postgres"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "notes"),
    "user": os.getenv("DB_USER", "notes"),
    "password": os.getenv("DB_PASSWORD", "notes_pw"),
    "connect_timeout": 3,
}

cache = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    socket_timeout=2,
    socket_connect_timeout=2,
    decode_responses=True,
)

CACHE_KEY = "notes:all"
CACHE_TTL = 30  # seconds


def get_db():
    return psycopg2.connect(**DB_CONFIG)


@app.get("/health")
def health():
    status = {"postgres": "ok", "redis": "ok"}
    code = 200
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
    except Exception as exc:
        log.error("health: postgres check failed: %s", exc)
        status["postgres"] = "down"
        code = 503
    try:
        cache.ping()
    except Exception as exc:
        log.error("health: redis check failed: %s", exc)
        status["redis"] = "down"
        code = 503
    return jsonify(status), code


@app.post("/notes")
def create_note():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    try:
        conn = get_db()
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notes (text) VALUES (%s) RETURNING id, created_at",
                (text,),
            )
            note_id, created_at = cur.fetchone()
        conn.close()
    except Exception as exc:
        log.error("create_note: database error: %s", exc)
        return jsonify({"error": "database unavailable"}), 500
    try:
        cache.delete(CACHE_KEY)  # invalidate cached list
    except Exception as exc:
        log.warning("create_note: cache invalidation failed: %s", exc)
    return jsonify({"id": note_id, "text": text, "created_at": created_at.isoformat()}), 201


@app.get("/notes")
def list_notes():
    try:
        cached = cache.get(CACHE_KEY)
        if cached:
            return jsonify({"source": "cache", "notes": json.loads(cached)})
    except Exception as exc:
        log.warning("list_notes: cache read failed: %s", exc)

    try:
        conn = get_db()
        with conn, conn.cursor() as cur:
            cur.execute("SELECT id, text, created_at FROM notes ORDER BY id DESC LIMIT 100")
            notes = [
                {"id": r[0], "text": r[1], "created_at": r[2].isoformat()}
                for r in cur.fetchall()
            ]
        conn.close()
    except Exception as exc:
        log.error("list_notes: database error: %s", exc)
        return jsonify({"error": "database unavailable"}), 500

    try:
        cache.setex(CACHE_KEY, CACHE_TTL, json.dumps(notes))
    except Exception as exc:
        log.warning("list_notes: cache write failed: %s", exc)
    return jsonify({"source": "db", "notes": notes})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
