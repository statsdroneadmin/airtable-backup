"""Local stand-in for nousviz_sdk — test harness only (sync.py is core's real file,
downloaded by tests/run.sh)."""
import contextlib, os
import psycopg2

DSN = os.environ.get("ATB_DSN", "host=127.0.0.1 port=55432 dbname=atb user=nousviz_plugin password=test")
CREDS: dict = {}
LOGS: list = []

@contextlib.contextmanager
def get_pg_conn():
    conn = psycopg2.connect(DSN)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

class DictCursor:
    def __init__(self, cur):
        self._c = cur
    def execute(self, *a, **k):
        return self._c.execute(*a, **k)
    def executemany(self, *a, **k):
        return self._c.executemany(*a, **k)
    def _d(self, row):
        return None if row is None else {d[0]: v for d, v in zip(self._c.description, row)}
    def fetchone(self):
        return self._d(self._c.fetchone())
    def fetchall(self):
        return [self._d(r) for r in self._c.fetchall()]

def dict_cursor(conn):
    return DictCursor(conn.cursor())

def get_credential(plugin_id, key, env_prefix=None):
    return CREDS.get(key)

def log_event(level, message, detail=None):
    LOGS.append((level, message, detail))
