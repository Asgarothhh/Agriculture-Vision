from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import sync_engine


def test_postgres_select_one():
    with sync_engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
        version = conn.execute(text("SELECT PostGIS_Version()")).scalar()
        assert version is not None


def test_redis_ping():
    import redis

    client = redis.from_url(get_settings().redis_url)
    assert client.ping() is True


def test_ready_and_health(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    ready = client.get("/api/v1/ready")
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"
    docs = client.get("/docs", follow_redirects=False)
    assert docs.status_code in {307, 302}
