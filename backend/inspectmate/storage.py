import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        for directory in ("images", "cache", "manifests", "detectors", "experiments"):
            (root / directory).mkdir(exist_ok=True)
        self.db = root / "inspectmate.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inspections(id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    category TEXT, method TEXT, decision TEXT, status TEXT, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_inspections_time ON inspections(created_at DESC);
                CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, inspection_id TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY, body TEXT);
            """)

    def connect(self):
        connection = sqlite3.connect(self.db, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def asset(self, data: bytes, image_hash: str, width: int, height: int, is_demo=False):
        asset_id = uuid.uuid4().hex
        (self.root / "images" / f"{asset_id}.png").write_bytes(data)
        record = {
            "asset_id": asset_id,
            "sample_id": f"sample_{asset_id[:16]}",
            "image_hash": image_hash,
            "width": width,
            "height": height,
            "is_demo_fixture": is_demo,
            "url": f"/api/assets/{asset_id}",
        }
        with self.connect() as db:
            db.execute("INSERT INTO assets VALUES (?, ?)", (asset_id, json.dumps(record)))
        return record

    def get_asset(self, asset_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise KeyError("이미지를 찾을 수 없습니다.")
        return json.loads(row[0])

    def asset_path(self, asset_id):
        self.get_asset(asset_id)
        return self.root / "images" / f"{asset_id}.png"

    def save_inspection(self, record):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO inspections VALUES (?,?,?,?,?,?,?)",
                (
                    record["inspection_id"],
                    record["created_at"],
                    record["category"],
                    record["method"],
                    record.get("final_decision"),
                    record["execution_status"],
                    json.dumps(record, ensure_ascii=False),
                ),
            )

    def inspection(self, inspection_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM inspections WHERE id=?", (inspection_id,)).fetchone()
        if not row:
            raise KeyError("검사를 찾을 수 없습니다.")
        return json.loads(row[0])

    def history(self, category=None, method=None, decision=None, status=None):
        query, args = "SELECT body FROM inspections WHERE 1=1", []
        for key, value in (
            ("category", category),
            ("method", method),
            ("decision", decision),
            ("status", status),
        ):
            if value:
                query += f" AND {key}=?"
                args.append(value)
        with self.connect() as db:
            rows = db.execute(query + " ORDER BY created_at DESC LIMIT 200", args).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_experiment(self, record):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?,?)",
                (record["experiment_id"], json.dumps(record)),
            )

    def experiment(self, experiment_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if not row:
            raise KeyError("실험을 찾을 수 없습니다.")
        return json.loads(row[0])

    def experiments(self):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM experiments ORDER BY rowid DESC LIMIT 50").fetchall()
        return [json.loads(row[0]) for row in rows]

    def recover_interrupted(self):
        """Single-process app startup: do not silently resume paid calls after a crash."""
        with self.connect() as db:
            rows = db.execute("SELECT body FROM inspections WHERE status='running'").fetchall()
        for row in rows:
            record = json.loads(row[0])
            record.update(
                execution_status="failed",
                error_code="process_interrupted",
                error_message="이전 서버 프로세스가 검사 중 종료되었습니다. 외부 요청 상태는 확인되지 않았습니다.",
            )
            self.save_inspection(record)
        for record in self.experiments():
            if record["status"] == "running":
                record.update(
                    status="interrupted",
                    error="서버 재시작으로 중단됨. 부분 predictions 파일을 보존했습니다.",
                    finished_at=now(),
                )
                self.save_experiment(record)
