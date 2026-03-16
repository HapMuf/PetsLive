import random
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from fastapi import HTTPException

from .config import SATIETY_ALERT_THRESHOLD
from .db import get_conn


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clamp(v, mn=0, mx=100):
    return max(mn, min(mx, v))


def get_all_pets():
    with closing(get_conn()) as conn:
        rows = conn.execute("SELECT * FROM pet ORDER BY id").fetchall()
        return [dict(row) for row in rows]


def save_pet(pet: dict):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE pet SET
                name = ?,
                satiety = ?,
                mood = ?,
                energy = ?,
                sleeping = ?,
                satiety_alert_30_sent = ?,
                updated_at = ?,
                owner_id = ?,
                care_type = ?
            WHERE id = ?
            """,
            (
                pet["name"],
                pet["satiety"],
                pet["mood"],
                pet["energy"],
                pet["sleeping"],
                pet["satiety_alert_30_sent"],
                pet["updated_at"],
                pet.get("owner_id"),
                pet.get("care_type", "solo"),
                pet["id"],
            ),
        )
        conn.commit()


def update_pet_state_for_one(pet: dict):
    if pet["sleeping"]:
        pet["energy"] = clamp(pet["energy"] + random.randint(1, 3))
        pet["satiety"] = clamp(pet["satiety"] - random.randint(0, 1))
        pet["mood"] = clamp(pet["mood"] - random.randint(0, 1))
    else:
        pet["satiety"] = clamp(pet["satiety"] - random.randint(1, 3))
        pet["mood"] = clamp(pet["mood"] - random.randint(0, 2))
        pet["energy"] = clamp(pet["energy"] - random.randint(0, 2))

    pet["satiety_alert_30_sent"] = 1 if pet["satiety"] <= SATIETY_ALERT_THRESHOLD else 0
    pet["updated_at"] = utc_now()
    save_pet(pet)


def get_pet_for_user(user_id: int, pet_id: int):
    with closing(get_conn()) as conn:
        access = conn.execute(
            """
            SELECT role FROM pet_access
            WHERE pet_id = ? AND user_id = ?
            """,
            (pet_id, user_id),
        ).fetchone()

        if access is None:
            raise HTTPException(status_code=403, detail="No access to this pet")

        pet = conn.execute("SELECT * FROM pet WHERE id = ?", (pet_id,)).fetchone()

        if pet is None:
            raise HTTPException(status_code=404, detail="Pet not found")

        return dict(pet)


def get_shared_usernames(conn: sqlite3.Connection, pet_id: int, exclude_user_id: int | None = None):
    params = [pet_id]
    sql = """
        SELECT users.username
        FROM pet_access
        JOIN users ON users.id = pet_access.user_id
        WHERE pet_access.pet_id = ?
          AND pet_access.role = 'parent'
    """

    if exclude_user_id is not None:
        sql += " AND pet_access.user_id != ?"
        params.append(exclude_user_id)

    sql += " ORDER BY users.username COLLATE NOCASE"

    rows = conn.execute(sql, tuple(params)).fetchall()
    return [row["username"] for row in rows]


def get_pet_payload_for_user(user_id: int, pet_id: int):
    with closing(get_conn()) as conn:
        access = conn.execute(
            """
            SELECT 1 FROM pet_access
            WHERE pet_id = ? AND user_id = ? AND role = 'parent'
            """,
            (pet_id, user_id),
        ).fetchone()

        if access is None:
            raise HTTPException(status_code=403, detail="No access to this pet")

        pet = conn.execute("SELECT * FROM pet WHERE id = ?", (pet_id,)).fetchone()

        if pet is None:
            raise HTTPException(status_code=404, detail="Pet not found")

        data = dict(pet)
        data["shared_with"] = get_shared_usernames(conn, pet_id, exclude_user_id=user_id)
        return data
