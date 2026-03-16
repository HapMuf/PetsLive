from fastapi import HTTPException, WebSocket


class ConnectionManager:
    def __init__(self):
        self.pet_connections: dict[int, list[dict]] = {}

    async def connect(self, pet_id: int, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.pet_connections.setdefault(pet_id, []).append(
            {"user_id": user_id, "websocket": websocket}
        )

    def disconnect(self, pet_id: int, websocket: WebSocket):
        if pet_id not in self.pet_connections:
            return

        self.pet_connections[pet_id] = [
            item
            for item in self.pet_connections[pet_id]
            if item["websocket"] is not websocket
        ]

        if not self.pet_connections[pet_id]:
            del self.pet_connections[pet_id]

    async def broadcast_pet_state(self, pet_id: int, payload_getter):
        if pet_id not in self.pet_connections:
            return

        dead_connections = []

        for item in list(self.pet_connections[pet_id]):
            websocket = item["websocket"]
            user_id = item["user_id"]

            try:
                payload = payload_getter(user_id, pet_id)
                await websocket.send_json(payload)
            except HTTPException:
                dead_connections.append(websocket)
            except Exception:
                dead_connections.append(websocket)

        for websocket in dead_connections:
            try:
                await websocket.close()
            except Exception:
                pass
            self.disconnect(pet_id, websocket)


manager = ConnectionManager()
