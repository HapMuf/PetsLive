from contextlib import closing

from fastapi import APIRouter, HTTPException

from auth import create_access_token, decode_access_token, hash_password, verify_password

from .db import get_conn
from .pet_service import utc_now
from .schemas import RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def get_user_id_from_token(token: str):
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


def get_user_id_from_auth_header(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    token = authorization[len("Bearer ") :].strip()
    return get_user_id_from_token(token)


@router.post("/register")
def register(data: RegisterRequest):
    with closing(get_conn()) as conn:
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (data.username,),
        ).fetchone()

        if existing_user is not None:
            raise HTTPException(status_code=400, detail="Username already exists")

        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, created_at)
            VALUES (?, ?, ?)
            """,
            (
                data.username,
                hash_password(data.password),
                utc_now(),
            ),
        )

        user_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO pet (
                name, satiety, mood, energy, sleeping,
                satiety_alert_30_sent, updated_at, owner_id, care_type
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{data.username}_pet",
                80,
                80,
                70,
                0,
                0,
                utc_now(),
                user_id,
                "solo",
            ),
        )

        pet_id = conn.execute(
            "SELECT id FROM pet WHERE owner_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO pet_access (pet_id, user_id, role, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                pet_id,
                user_id,
                "parent",
                utc_now(),
            ),
        )

        conn.commit()

        access_token = create_access_token(user_id)

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": data.username,
        }


@router.post("/login")
def login(data: RegisterRequest):
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (data.username,),
        ).fetchone()

        if user is None:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        if not verify_password(data.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        access_token = create_access_token(user["id"])

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user["id"],
            "username": user["username"],
        }
