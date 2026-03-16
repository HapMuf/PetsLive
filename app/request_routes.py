from contextlib import closing

from fastapi import APIRouter, Header, HTTPException

from .auth_routes import get_user_id_from_auth_header
from .db import get_conn
from .pet_service import utc_now
from .pet_routes import broadcast_pet_state
from .schemas import InviteRequest

router = APIRouter(tags=["requests"])


@router.post("/pets/invite")
def invite_user(
    data: InviteRequest,
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id"),
):
    user_id = get_user_id_from_auth_header(authorization)

    if pet_id is None:
        raise HTTPException(status_code=400, detail="Missing pet id")

    with closing(get_conn()) as conn:
        my_access = conn.execute(
            """
            SELECT id FROM pet_access
            WHERE pet_id = ? AND user_id = ? AND role = 'parent'
            """,
            (pet_id, user_id),
        ).fetchone()

        if my_access is None:
            raise HTTPException(status_code=403, detail="Only a parent can invite")

        target_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (data.username,),
        ).fetchone()

        if target_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        target_user_id = target_user["id"]

        if target_user_id == user_id:
            raise HTTPException(status_code=400, detail="Cannot invite yourself")

        existing_access = conn.execute(
            "SELECT id FROM pet_access WHERE pet_id = ? AND user_id = ?",
            (pet_id, target_user_id),
        ).fetchone()

        if existing_access:
            raise HTTPException(status_code=400, detail="User already has access")

        existing_request = conn.execute(
            """
            SELECT id FROM pet_requests
            WHERE pet_id = ?
              AND to_user_id = ?
              AND request_type = 'parent_invite'
              AND status = 'pending'
            """,
            (pet_id, target_user_id),
        ).fetchone()

        if existing_request:
            raise HTTPException(status_code=400, detail="Invitation already pending")

        conn.execute(
            """
            INSERT INTO pet_requests (
                pet_id, from_user_id, to_user_id, request_type, status, created_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (pet_id, user_id, target_user_id, "parent_invite", utc_now()),
        )

        conn.commit()
        return {"status": "pending_invite_created"}


@router.get("/requests/incoming")
def get_incoming_requests(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT
                pet_requests.id,
                pet_requests.pet_id,
                pet_requests.request_type,
                pet_requests.status,
                pet_requests.created_at,
                pet.name AS pet_name,
                users.username AS from_username
            FROM pet_requests
            JOIN pet ON pet.id = pet_requests.pet_id
            JOIN users ON users.id = pet_requests.from_user_id
            WHERE pet_requests.to_user_id = ?
            ORDER BY pet_requests.id DESC
            """,
            (user_id,),
        ).fetchall()

        return [dict(row) for row in rows]


@router.get("/requests/outgoing")
def get_outgoing_requests(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT
                pet_requests.id,
                pet_requests.pet_id,
                pet_requests.request_type,
                pet_requests.status,
                pet_requests.created_at,
                pet_requests.responded_at,
                pet.name AS pet_name,
                users.username AS to_username
            FROM pet_requests
            JOIN pet ON pet.id = pet_requests.pet_id
            JOIN users ON users.id = pet_requests.to_user_id
            WHERE pet_requests.from_user_id = ?
            ORDER BY pet_requests.id DESC
            """,
            (user_id,),
        ).fetchall()

        return [dict(row) for row in rows]


@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: int, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    affected_pet_id = None

    with closing(get_conn()) as conn:
        request_row = conn.execute(
            "SELECT * FROM pet_requests WHERE id = ?",
            (request_id,),
        ).fetchone()

        if request_row is None:
            raise HTTPException(status_code=404, detail="Request not found")

        if request_row["to_user_id"] != user_id:
            raise HTTPException(status_code=403, detail="This request is not for you")

        if request_row["status"] != "pending":
            raise HTTPException(status_code=400, detail="Request is not pending")

        affected_pet_id = request_row["pet_id"]

        if request_row["request_type"] == "parent_invite":
            existing_access = conn.execute(
                "SELECT id FROM pet_access WHERE pet_id = ? AND user_id = ?",
                (request_row["pet_id"], user_id),
            ).fetchone()

            if existing_access is None:
                conn.execute(
                    """
                    INSERT INTO pet_access (pet_id, user_id, role, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (request_row["pet_id"], user_id, "parent", utc_now()),
                )

            conn.execute(
                "UPDATE pet SET care_type = 'shared' WHERE id = ?",
                (request_row["pet_id"],),
            )

        elif request_row["request_type"] == "unshare_request":
            sender_access = conn.execute(
                "SELECT id FROM pet_access WHERE pet_id = ? AND user_id = ?",
                (request_row["pet_id"], request_row["from_user_id"]),
            ).fetchone()

            if sender_access is not None:
                conn.execute(
                    "DELETE FROM pet_access WHERE pet_id = ? AND user_id = ?",
                    (request_row["pet_id"], request_row["from_user_id"]),
                )

            parent_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM pet_access WHERE pet_id = ? AND role = 'parent'",
                (request_row["pet_id"],),
            ).fetchone()["cnt"]

            if parent_count <= 1:
                conn.execute(
                    "UPDATE pet SET care_type = 'solo' WHERE id = ?",
                    (request_row["pet_id"],),
                )

        else:
            raise HTTPException(status_code=400, detail="Unsupported request type")

        conn.execute(
            "UPDATE pet_requests SET status = 'accepted', responded_at = ? WHERE id = ?",
            (utc_now(), request_id),
        )

        conn.commit()

    if affected_pet_id is not None:
        await broadcast_pet_state(affected_pet_id)

    return {"status": "accepted"}


@router.post("/requests/{request_id}/decline")
def decline_request(request_id: int, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        request_row = conn.execute(
            "SELECT * FROM pet_requests WHERE id = ?",
            (request_id,),
        ).fetchone()

        if request_row is None:
            raise HTTPException(status_code=404, detail="Request not found")

        if request_row["to_user_id"] != user_id:
            raise HTTPException(status_code=403, detail="This request is not for you")

        if request_row["status"] != "pending":
            raise HTTPException(status_code=400, detail="Request is not pending")

        conn.execute(
            "UPDATE pet_requests SET status = 'declined', responded_at = ? WHERE id = ?",
            (utc_now(), request_id),
        )
        conn.commit()

        return {"status": "declined"}


@router.post("/pets/{pet_id}/unshare-request")
def create_unshare_request(pet_id: int, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        my_access = conn.execute(
            "SELECT id FROM pet_access WHERE pet_id = ? AND user_id = ? AND role = 'parent'",
            (pet_id, user_id),
        ).fetchone()

        if my_access is None:
            raise HTTPException(status_code=403, detail="Only a parent can request unsharing")

        other_parent = conn.execute(
            "SELECT user_id FROM pet_access WHERE pet_id = ? AND role = 'parent' AND user_id != ? ORDER BY id LIMIT 1",
            (pet_id, user_id),
        ).fetchone()

        if other_parent is None:
            raise HTTPException(status_code=400, detail="No second parent to unshare with")

        existing_request = conn.execute(
            """
            SELECT id FROM pet_requests
            WHERE pet_id = ?
              AND from_user_id = ?
              AND to_user_id = ?
              AND request_type = 'unshare_request'
              AND status = 'pending'
            """,
            (pet_id, user_id, other_parent["user_id"]),
        ).fetchone()

        if existing_request:
            raise HTTPException(status_code=400, detail="Unshare request already pending")

        conn.execute(
            """
            INSERT INTO pet_requests (
                pet_id, from_user_id, to_user_id, request_type, status, created_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (pet_id, user_id, other_parent["user_id"], "unshare_request", utc_now()),
        )

        conn.commit()
        return {"status": "pending_unshare_created"}
