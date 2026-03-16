import asyncio
import random

from fastapi import APIRouter, Header, HTTPException, Query, WebSocket, WebSocketDisconnect

from .auth_routes import get_user_id_from_auth_header, get_user_id_from_token
from .config import TICK_SECONDS
from .pet_service import (
    clamp,
    get_all_pets,
    get_pet_for_user,
    get_pet_payload_for_user,
    save_pet,
    update_pet_state_for_one,
    utc_now,
)
from .websocket_manager import manager

router = APIRouter(tags=["pets"])


async def broadcast_pet_state(pet_id: int):
    await manager.broadcast_pet_state(pet_id, get_pet_payload_for_user)


async def update_all_pets_state():
    pets = get_all_pets()
    for pet in pets:
        update_pet_state_for_one(pet)
        await broadcast_pet_state(pet["id"])


async def pet_loop():
    while True:
        await asyncio.sleep(TICK_SECONDS)
        await update_all_pets_state()


@router.websocket("/ws/pets/{pet_id}")
async def websocket_pet(websocket: WebSocket, pet_id: int, token: str = Query(...)):
    try:
        user_id = get_user_id_from_token(token)
        payload = get_pet_payload_for_user(user_id, pet_id)
    except HTTPException:
        await websocket.close(code=1008)
        return

    await manager.connect(pet_id, user_id, websocket)

    try:
        await websocket.send_json(payload)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(pet_id, websocket)
    except Exception:
        manager.disconnect(pet_id, websocket)
        try:
            await websocket.close()
        except Exception:
            pass


@router.post("/pet/feed")
async def feed_pet(
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id"),
):
    user_id = get_user_id_from_auth_header(authorization)

    if pet_id is None:
        raise HTTPException(status_code=400, detail="Missing pet id")

    pet = get_pet_for_user(user_id, pet_id)
    pet["satiety"] = clamp(pet["satiety"] + random.randint(8, 15))
    pet["mood"] = clamp(pet["mood"] + random.randint(1, 4))
    pet["updated_at"] = utc_now()
    save_pet(pet)

    await broadcast_pet_state(pet_id)
    return get_pet_payload_for_user(user_id, pet_id)


@router.post("/pet/play")
async def play_with_pet(
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id"),
):
    user_id = get_user_id_from_auth_header(authorization)

    if pet_id is None:
        raise HTTPException(status_code=400, detail="Missing pet id")

    pet = get_pet_for_user(user_id, pet_id)

    if pet["sleeping"]:
        raise HTTPException(status_code=400, detail="Pet is sleeping")

    pet["mood"] = clamp(pet["mood"] + random.randint(6, 12))
    pet["energy"] = clamp(pet["energy"] - random.randint(4, 8))
    pet["satiety"] = clamp(pet["satiety"] - random.randint(2, 5))
    pet["updated_at"] = utc_now()
    save_pet(pet)

    await broadcast_pet_state(pet_id)
    return get_pet_payload_for_user(user_id, pet_id)


@router.post("/pet/sleep")
async def put_pet_to_sleep(
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id"),
):
    user_id = get_user_id_from_auth_header(authorization)

    if pet_id is None:
        raise HTTPException(status_code=400, detail="Missing pet id")

    pet = get_pet_for_user(user_id, pet_id)
    pet["sleeping"] = 1
    pet["updated_at"] = utc_now()
    save_pet(pet)

    await broadcast_pet_state(pet_id)
    return get_pet_payload_for_user(user_id, pet_id)


@router.post("/pet/wake")
async def wake_pet(
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id"),
):
    user_id = get_user_id_from_auth_header(authorization)

    if pet_id is None:
        raise HTTPException(status_code=400, detail="Missing pet id")

    pet = get_pet_for_user(user_id, pet_id)
    pet["sleeping"] = 0
    pet["updated_at"] = utc_now()
    save_pet(pet)

    await broadcast_pet_state(pet_id)
    return get_pet_payload_for_user(user_id, pet_id)


@router.get("/pets/my")
def get_my_pet(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    from .db import get_conn
    from contextlib import closing

    with closing(get_conn()) as conn:
        pet = conn.execute(
            "SELECT id FROM pet WHERE owner_id = ? ORDER BY id LIMIT 1",
            (user_id,),
        ).fetchone()

        if pet is None:
            raise HTTPException(status_code=404, detail="Pet not found")

        return get_pet_payload_for_user(user_id, pet["id"])


@router.get("/pets")
def get_my_pets(authorization: str | None = Header(default=None)):
    from .db import get_conn
    from contextlib import closing

    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT pet.id
            FROM pet
            JOIN pet_access ON pet.id = pet_access.pet_id
            WHERE pet_access.user_id = ? AND pet_access.role = 'parent'
            ORDER BY pet.id
            """,
            (user_id,),
        ).fetchall()

    return [get_pet_payload_for_user(user_id, row["id"]) for row in rows]


@router.get("/pets/{pet_id}")
def get_pet_by_id(pet_id: int, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    return get_pet_payload_for_user(user_id, pet_id)
