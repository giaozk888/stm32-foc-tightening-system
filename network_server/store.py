from __future__ import annotations
import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Union
from network_server.schema import RANGES, validate

class Conflict(ValueError):
    pass

class Store:
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = self.connection()
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS observations(
                id INTEGER PRIMARY KEY, device TEXT NOT NULL, session TEXT NOT NULL,
                seq INTEGER NOT NULL, received_at TEXT NOT NULL, kind INTEGER NOT NULL,
                run INTEGER NOT NULL, cycle INTEGER NOT NULL, payload TEXT NOT NULL,
                UNIQUE(device,session,seq))""")
            db.execute("CREATE INDEX IF NOT EXISTS obs_result ON observations(kind,id)")
            db.execute("CREATE INDEX IF NOT EXISTS obs_device ON observations(device,id)")
            db.commit()
        finally:
            db.close()

    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        # Commit acknowledgement follows durable WAL commit.
        db.execute("PRAGMA synchronous=FULL")
        return db

    def ingest(self, packet: object) -> dict:
        p = validate(packet)
        s = p["sample"]
        text = json.dumps(p, sort_keys=True, separators=(",", ":"))
        # Close connections explicitly: sqlite context manager only commits.
        db = self.connection()
        try:
            with db:
                cursor = db.execute("""INSERT OR IGNORE INTO observations
                    (device,session,seq,received_at,kind,run,cycle,payload)
                    VALUES(?,?,?,?,?,?,?,?)""", (p["device"], p["session"], s["seq"],
                    datetime.now(timezone.utc).isoformat(), s["kind"], s["run"], s["cycle"], text))
                inserted = cursor.rowcount == 1
                row = db.execute("SELECT id,payload FROM observations WHERE device=? AND session=? AND seq=?",
                                 (p["device"], p["session"], s["seq"])).fetchone()
                if row["payload"] != text:
                    raise Conflict("event key already has different data")
            return {"ack": {"session": p["session"], "seq": s["seq"]},
                    "id": row["id"], "inserted": inserted, "control_enabled": False}
        finally:
            db.close()

    def records(self, after=0, limit=100, kind=None):
        if not 0 <= after or not 1 <= limit <= 500 or kind not in (None, 0, 1):
            raise ValueError("invalid query")
        db = self.connection()
        try:
            where = "id>?" + (" AND kind=?" if kind is not None else "")
            params = [after] + ([kind] if kind is not None else []) + [limit]
            rows = db.execute(f"SELECT * FROM observations WHERE {where} ORDER BY id LIMIT ?", params).fetchall()
            return [{"id": r["id"], "received_at": r["received_at"],
                     **json.loads(r["payload"])} for r in rows]
        finally:
            db.close()

    def summary(self):
        db = self.connection()
        try:
            n = db.execute("SELECT COUNT(*) n,SUM(kind=1) results FROM observations").fetchone()
            latest = db.execute("SELECT MAX(id) id FROM observations GROUP BY device").fetchall()
            devices = []
            for item in latest:
                row = db.execute("SELECT payload,received_at FROM observations WHERE id=?", (item["id"],)).fetchone()
                devices.append({**json.loads(row["payload"]), "received_at": row["received_at"]})
            return {"samples": n["n"], "results": n["results"] or 0,
                    "devices": devices, "control_enabled": False,
                    "note": "诊断估值；Iq不是实测扭矩；时间为服务器接收时间"}
        finally:
            db.close()

    def csv_bytes(self, after=0, limit=500, kind=None):
        rows = self.records(after, limit, kind)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["id", "received_at", "device", "session", *RANGES])
        for r in rows:
            writer.writerow([r["id"], r["received_at"], r["device"], r["session"],
                             *(r["sample"][k] for k in RANGES)])
        return output.getvalue().encode("utf-8-sig")
