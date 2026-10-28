"""Test-only SQLAlchemy-Connection look-alike that executes the app's real SQL against a real
PostgreSQL through the `psql` client. It exists so the SQL layer can be exercised where the
psycopg driver cannot be installed. With the real dependencies installed you can ignore it and use
a normal SQLAlchemy engine (see README).

Enable with env PROOFLINE_TEST_PSQL="host=/tmp port=54329 user=proofline dbname=proofline_test".
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import re
import subprocess
import uuid

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def enabled() -> bool:
    return bool(os.getenv("PROOFLINE_TEST_PSQL"))


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float, decimal.Decimal)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "'{}'::text[]" if not v else "ARRAY[" + ",".join(_lit(x) for x in v) + "]::text[]"
    if isinstance(v, (uuid.UUID, dt.date, dt.datetime)):
        v = v.isoformat() if not isinstance(v, uuid.UUID) else str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _decode(o):
    if isinstance(o, dict):
        return {k: _decode(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_decode(v) for v in o]
    if isinstance(o, str) and _UUID_RE.match(o):
        return uuid.UUID(o)
    return o


class _Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None


class PsqlConn:
    def __init__(self):
        kv = dict(p.split("=", 1) for p in os.environ["PROOFLINE_TEST_PSQL"].split())
        self.p = subprocess.Popen(
            ["psql", "-X", "-q", "-A", "-t", "-h", kv["host"], "-p", kv["port"], "-U", kv["user"], "-d", kv["dbname"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self._run("BEGIN")

    def _run(self, sql: str) -> list[str]:
        self.p.stdin.write(sql.rstrip().rstrip(";") + ";\n\\echo __END__\n")
        self.p.stdin.flush()
        lines = []
        while True:
            line = self.p.stdout.readline()
            if line == "" or line.strip() == "__END__":
                break
            lines.append(line.rstrip("\n"))
        errs = [l for l in lines if l.startswith("ERROR:") or "ERROR:" in l[:12]]
        if errs:
            raise RuntimeError(errs[0])
        return lines

    def execute(self, sql, params=None):
        params = params or {}
        bound = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", lambda m: _lit(params[m.group(1)]), sql)
        low = bound.lstrip().lower()
        if low.startswith(("select", "with")) and "returning" not in low.split("select", 1)[0] + low:
            out = self._run(f"select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from ({bound}) t")
        elif "returning" in low:
            out = self._run(f"with t as ({bound}) select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from t")
        else:
            self._run(bound)
            return _Result([])
        return _Result(_decode(json.loads(out[-1])))

    def commit(self):
        self._run("COMMIT")

    def rollback(self):
        try:
            self._run("ROLLBACK")
        except RuntimeError:
            pass

    def close(self):
        try:
            self.p.stdin.write("\\q\n"); self.p.stdin.flush()
        except Exception:
            pass
        self.p.wait(timeout=10)

    def __enter__(self): return self

    def __exit__(self, et, ev, tb):
        self.rollback() if et else self.commit()
        self.close()
        return False
