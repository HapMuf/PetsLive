import sqlite3
from contextlib import closing

from .config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def init_db():
    with closing(get_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pet (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                satiety INTEGER,
                mood INTEGER,
                energy INTEGER,
                sleeping INTEGER,
                satiety_alert_30_sent INTEGER,
                updated_at TEXT,
                owner_id INTEGER,
                care_type TEXT NOT NULL DEFAULT 'solo'
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pet_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pet_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pet_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pet_id INTEGER NOT NULL,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                request_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                responded_at TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pet_requests_to_user_status
            ON pet_requests(to_user_id, status)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pet_requests_pet_id
            ON pet_requests(pet_id)
            """
        )

        if not column_exists(conn, "pet", "owner_id"):
            conn.execute("ALTER TABLE pet ADD COLUMN owner_id INTEGER")

        if not column_exists(conn, "pet", "care_type"):
            conn.execute("ALTER TABLE pet ADD COLUMN care_type TEXT NOT NULL DEFAULT 'solo'")

        conn.commit()
