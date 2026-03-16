from contextlib import closing

from fastapi import APIRouter, Header, HTTPException

from .auth_routes import get_user_id_from_auth_header
from .db import get_conn

router = APIRouter(tags=["users"])


@router.get("/users/me")
def get_me(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        return dict(user)
