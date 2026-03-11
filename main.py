import asyncio
import random
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from auth import hash_password, create_access_token, verify_password, decode_access_token
from pydantic import BaseModel

DB_PATH = "/opt/tamagotchi/tamagotchi.db"
TICK_SECONDS = 60
SATIETY_ALERT_THRESHOLD = 30

app = FastAPI(title="Tamagotchi Server")


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
            item for item in self.pet_connections[pet_id]
            if item["websocket"] is not websocket
        ]

        if not self.pet_connections[pet_id]:
            del self.pet_connections[pet_id]

    async def broadcast_pet_state(self, pet_id: int):
        if pet_id not in self.pet_connections:
            return

        dead_connections = []

        for item in list(self.pet_connections[pet_id]):
            websocket = item["websocket"]
            user_id = item["user_id"]

            try:
                payload = get_pet_payload_for_user(user_id, pet_id)
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


class RegisterRequest(BaseModel):
    username: str
    password: str


class InviteRequest(BaseModel):
    username: str


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clamp(v, mn=0, mx=100):
    return max(mn, min(mx, v))


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_user_id_from_auth_header(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    token = authorization[len("Bearer "):].strip()
    return get_user_id_from_token(token)


def get_user_id_from_token(token: str):
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


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
            (pet_id, user_id)
        ).fetchone()

        if access is None:
            raise HTTPException(status_code=403, detail="No access to this pet")

        pet = conn.execute(
            "SELECT * FROM pet WHERE id = ?",
            (pet_id,)
        ).fetchone()

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
            (pet_id, user_id)
        ).fetchone()

        if access is None:
            raise HTTPException(status_code=403, detail="No access to this pet")

        pet = conn.execute(
            "SELECT * FROM pet WHERE id = ?",
            (pet_id,)
        ).fetchone()

        if pet is None:
            raise HTTPException(status_code=404, detail="Pet not found")

        data = dict(pet)
        data["shared_with"] = get_shared_usernames(conn, pet_id, exclude_user_id=user_id)
        return data


async def update_all_pets_state():
    pets = get_all_pets()
    for pet in pets:
        update_pet_state_for_one(pet)
        await manager.broadcast_pet_state(pet["id"])


async def pet_loop():
    while True:
        await asyncio.sleep(TICK_SECONDS)
        await update_all_pets_state()


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(pet_loop())


@app.get("/")
def root():
    return {"status": "ok"}


@app.websocket("/ws/pets/{pet_id}")
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


@app.get("/pet/view", response_class=HTMLResponse)
def pet_view():
    return """
    <html>
        <head>
            <title>Tamagotchi</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: Arial; max-width: 600px; margin: 40px auto;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h1>Мой питомец</h1>
                <div style="display:flex; gap:8px;">
                    <button onclick="window.location.href='/pets/select'">Сменить питомца</button>
                    <button onclick="logout()">Выйти</button>
                </div>
            </div>

            <p id="user" style="color:gray;"></p>

            <div id="pet">Загрузка...</div>

            <div style="margin-top: 20px; display: flex; gap: 10px; flex-wrap: wrap;">
                <button onclick="action('/pet/feed')">Покормить</button>
                <button onclick="action('/pet/play')">Поиграть</button>
                <button onclick="action('/pet/sleep')">Уложить спать</button>
                <button onclick="action('/pet/wake')">Разбудить</button>
            </div>

            <div style="margin-top: 24px; border:1px solid #ddd; padding:12px;">
                <p><b>Совместное воспитание</b></p>
                <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                    <input id="inviteUsername" type="text" placeholder="Логин пользователя" style="padding:8px;" />
                    <button onclick="inviteUser()">Пригласить</button>
                    <button onclick="openRequests()">Открыть запросы</button>
                    <button onclick="requestUnshare()">Предложить расторгнуть</button>
                </div>
            </div>

            <p id="message" style="margin-top: 16px;"></p>

            <script>
                let petSocket = null;
                let reconnectTimer = null;

                function logout() {
                    localStorage.removeItem("access_token");
                    window.location.href = "/login";
                }

                function openRequests() {
                    window.location.href = "/requests/view";
                }

                async function inviteUser() {
                    const token = localStorage.getItem("access_token");
                    const petId = localStorage.getItem("selected_pet_id");
                    const username = document.getElementById("inviteUsername").value;

                    const response = await fetch("/pets/invite", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "Authorization": "Bearer " + token,
                            "X-Pet-Id": petId
                        },
                        body: JSON.stringify({ username })
                    });

                    const data = await response.json();
                    document.getElementById("message").innerText = response.ok
                        ? "Приглашение отправлено"
                        : (data.detail || "Ошибка");
                }

                async function requestUnshare() {
                    const token = localStorage.getItem("access_token");
                    const petId = localStorage.getItem("selected_pet_id");

                    const response = await fetch(`/pets/${petId}/unshare-request`, {
                        method: "POST",
                        headers: {
                            "Authorization": "Bearer " + token
                        }
                    });

                    const data = await response.json();
                    document.getElementById("message").innerText = response.ok
                        ? "Запрос на расторжение отправлен"
                        : (data.detail || "Ошибка");
                }

                async function loadUser() {
                    const token = localStorage.getItem("access_token");

                    const response = await fetch("/users/me", {
                        headers: {
                            "Authorization": "Bearer " + token
                        }
                    });

                    if (response.ok) {
                        const user = await response.json();
                        document.getElementById("user").innerText = "Вы вошли как: " + user.username;
                    }
                }

                function renderPet(pet) {
                    const sleepingText = pet.sleeping ? "Да 😴" : "Нет 🙂";
                    const careTypeText = pet.care_type === "shared" ? "совместное" : "одиночное";
                    const updatedText = new Date(pet.updated_at).toLocaleString("ru-RU", {
                        day: "2-digit",
                        month: "2-digit",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit"
                    });

                    let sharedHtml = "";
                    if (pet.care_type === "shared" && pet.shared_with && pet.shared_with.length > 0) {
                        sharedHtml = `<p><b>Совместно с:</b> ${pet.shared_with.join(", ")}</p>`;
                    }

                    document.getElementById("pet").innerHTML = `
                        <p><b>Имя:</b> ${pet.name}</p>
                        <p><b>Воспитание:</b> ${careTypeText}</p>
                        ${sharedHtml}
                        <p><b>Сытость:</b> ${pet.satiety}</p>
                        <p><b>Настроение:</b> ${pet.mood}</p>
                        <p><b>Энергия:</b> ${pet.energy}</p>
                        <p><b>Спит:</b> ${sleepingText}</p>
                        <p><b>Обновлён:</b> ${updatedText}</p>
                    `;
                }

                function connectPetSocket() {
                    const token = localStorage.getItem("access_token");
                    const petId = localStorage.getItem("selected_pet_id");

                    if (!token) {
                        window.location.href = "/login";
                        return;
                    }

                    if (!petId) {
                        window.location.href = "/pets/select";
                        return;
                    }

                    if (petSocket) {
                        petSocket.close();
                    }

                    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
                    petSocket = new WebSocket(`${protocol}://${window.location.host}/ws/pets/${petId}?token=${encodeURIComponent(token)}`);

                    petSocket.onopen = () => {
                        if (petSocket._heartbeat) {
                            clearInterval(petSocket._heartbeat);
                        }
                        petSocket._heartbeat = setInterval(() => {
                            if (petSocket && petSocket.readyState === WebSocket.OPEN) {
                                petSocket.send("ping");
                            }
                        }, 20000);
                    };

                    petSocket.onmessage = (event) => {
                        const pet = JSON.parse(event.data);
                        renderPet(pet);
                    };

                    petSocket.onclose = () => {
                        if (petSocket && petSocket._heartbeat) {
                            clearInterval(petSocket._heartbeat);
                        }
                        if (reconnectTimer) {
                            clearTimeout(reconnectTimer);
                        }
                        reconnectTimer = setTimeout(connectPetSocket, 2000);
                    };

                    petSocket.onerror = () => {
                        if (petSocket) {
                            petSocket.close();
                        }
                    };
                }

                async function action(url) {
                    const token = localStorage.getItem("access_token");
                    const petId = localStorage.getItem("selected_pet_id");

                    if (!token) {
                        window.location.href = "/login";
                        return;
                    }

                    const response = await fetch(url, {
                        method: "POST",
                        headers: {
                            "Authorization": "Bearer " + token,
                            "X-Pet-Id": petId
                        }
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        document.getElementById("message").innerText = data.detail || "Ошибка действия";
                        return;
                    }

                    document.getElementById("message").innerText = "Действие выполнено";
                }

                loadUser();
                connectPetSocket();
            </script>
        </body>
    </html>
    """


@app.post("/pet/feed")
async def feed_pet(
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id")
):
    user_id = get_user_id_from_auth_header(authorization)

    if pet_id is None:
        raise HTTPException(status_code=400, detail="Missing pet id")

    pet = get_pet_for_user(user_id, pet_id)
    pet["satiety"] = clamp(pet["satiety"] + random.randint(8, 15))
    pet["mood"] = clamp(pet["mood"] + random.randint(1, 4))
    pet["updated_at"] = utc_now()
    save_pet(pet)

    await manager.broadcast_pet_state(pet_id)
    return get_pet_payload_for_user(user_id, pet_id)


@app.post("/pet/play")
async def play_with_pet(
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id")
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

    await manager.broadcast_pet_state(pet_id)
    return get_pet_payload_for_user(user_id, pet_id)


@app.post("/pet/sleep")
async def put_pet_to_sleep(
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id")
):
    user_id = get_user_id_from_auth_header(authorization)

    if pet_id is None:
        raise HTTPException(status_code=400, detail="Missing pet id")

    pet = get_pet_for_user(user_id, pet_id)
    pet["sleeping"] = 1
    pet["updated_at"] = utc_now()
    save_pet(pet)

    await manager.broadcast_pet_state(pet_id)
    return get_pet_payload_for_user(user_id, pet_id)


@app.post("/pet/wake")
async def wake_pet(
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id")
):
    user_id = get_user_id_from_auth_header(authorization)

    if pet_id is None:
        raise HTTPException(status_code=400, detail="Missing pet id")

    pet = get_pet_for_user(user_id, pet_id)
    pet["sleeping"] = 0
    pet["updated_at"] = utc_now()
    save_pet(pet)

    await manager.broadcast_pet_state(pet_id)
    return get_pet_payload_for_user(user_id, pet_id)


@app.post("/auth/register")
def register(data: RegisterRequest):
    with closing(get_conn()) as conn:
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (data.username,)
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
            )
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
            )
        )

        pet_id = conn.execute(
            "SELECT id FROM pet WHERE owner_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
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
            )
        )

        conn.commit()

        access_token = create_access_token(user_id)

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": data.username,
        }


@app.post("/auth/login")
def login(data: RegisterRequest):
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (data.username,)
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


@app.get("/pets/my")
def get_my_pet(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        pet = conn.execute(
            "SELECT id FROM pet WHERE owner_id = ? ORDER BY id LIMIT 1",
            (user_id,)
        ).fetchone()

        if pet is None:
            raise HTTPException(status_code=404, detail="Pet not found")

        return get_pet_payload_for_user(user_id, pet["id"])


@app.get("/users/me")
def get_me(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        return dict(user)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <html>
        <head>
            <title>Login - Tamagotchi</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: Arial; max-width: 420px; margin: 40px auto;">
            <h1>Вход</h1>

            <form id="login-form">
                <div style="margin-bottom: 12px;">
                    <label>Логин</label><br>
                    <input id="username" type="text" style="width: 100%; padding: 8px;" />
                </div>

                <div style="margin-bottom: 12px;">
                    <label>Пароль</label><br>
                    <input id="password" type="password" style="width: 100%; padding: 8px;" />
                </div>

                <button type="submit" style="padding: 10px 16px;">Войти</button>
            </form>

            <p id="result" style="margin-top: 16px;"></p>

            <p style="margin-top: 20px;">
                Нет аккаунта? <a href="/register">Зарегистрироваться</a>
            </p>

            <script>
                const form = document.getElementById("login-form");
                const result = document.getElementById("result");

                form.addEventListener("submit", async (e) => {
                    e.preventDefault();

                    const username = document.getElementById("username").value;
                    const password = document.getElementById("password").value;

                    const response = await fetch("/auth/login", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ username, password })
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        result.innerText = data.detail || "Ошибка входа";
                        return;
                    }

                    localStorage.setItem("access_token", data.access_token);
                    window.location.href = "/pet/view";
                });
            </script>
        </body>
    </html>
    """


@app.get("/register", response_class=HTMLResponse)
def register_page():
    return """
    <html>
        <head>
            <title>Register - Tamagotchi</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: Arial; max-width: 420px; margin: 40px auto;">
            <h1>Регистрация</h1>

            <form id="register-form">
                <div style="margin-bottom: 12px;">
                    <label>Логин</label><br>
                    <input id="username" type="text" style="width: 100%; padding: 8px;" />
                </div>

                <div style="margin-bottom: 12px;">
                    <label>Пароль</label><br>
                    <input id="password" type="password" style="width: 100%; padding: 8px;" />
                </div>

                <button type="submit" style="padding: 10px 16px;">Зарегистрироваться</button>
            </form>

            <p id="result" style="margin-top: 16px;"></p>

            <p style="margin-top: 20px;">
                Уже есть аккаунт? <a href="/login">Войти</a>
            </p>

            <script>
                const form = document.getElementById("register-form");
                const result = document.getElementById("result");

                form.addEventListener("submit", async (e) => {
                    e.preventDefault();

                    const username = document.getElementById("username").value;
                    const password = document.getElementById("password").value;

                    const response = await fetch("/auth/register", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ username, password })
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        result.innerText = data.detail || "Ошибка регистрации";
                        return;
                    }

                    localStorage.setItem("access_token", data.access_token);
                    window.location.href = "/pet/view";
                });
            </script>
        </body>
    </html>
    """


@app.post("/pets/invite")
def invite_user(
    data: InviteRequest,
    authorization: str | None = Header(default=None),
    pet_id: int | None = Header(default=None, alias="X-Pet-Id")
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
            (pet_id, user_id)
        ).fetchone()

        if my_access is None:
            raise HTTPException(status_code=403, detail="Only a parent can invite")

        target_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (data.username,)
        ).fetchone()

        if target_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        target_user_id = target_user["id"]

        if target_user_id == user_id:
            raise HTTPException(status_code=400, detail="Cannot invite yourself")

        existing_access = conn.execute(
            "SELECT id FROM pet_access WHERE pet_id = ? AND user_id = ?",
            (pet_id, target_user_id)
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
            (pet_id, target_user_id)
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
            (pet_id, user_id, target_user_id, 'parent_invite', utc_now())
        )

        conn.commit()
        return {"status": "pending_invite_created"}


@app.get("/requests/incoming")
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
            (user_id,)
        ).fetchall()

        return [dict(row) for row in rows]


@app.get("/requests/outgoing")
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
            (user_id,)
        ).fetchall()

        return [dict(row) for row in rows]


@app.post("/requests/{request_id}/accept")
async def accept_request(request_id: int, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    affected_pet_id = None

    with closing(get_conn()) as conn:
        request_row = conn.execute(
            "SELECT * FROM pet_requests WHERE id = ?",
            (request_id,)
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
                (request_row["pet_id"], user_id)
            ).fetchone()

            if existing_access is None:
                conn.execute(
                    """
                    INSERT INTO pet_access (pet_id, user_id, role, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (request_row["pet_id"], user_id, "parent", utc_now())
                )

            conn.execute(
                "UPDATE pet SET care_type = 'shared' WHERE id = ?",
                (request_row["pet_id"],)
            )

        elif request_row["request_type"] == "unshare_request":
            sender_access = conn.execute(
                "SELECT id FROM pet_access WHERE pet_id = ? AND user_id = ?",
                (request_row["pet_id"], request_row["from_user_id"])
            ).fetchone()

            if sender_access is not None:
                conn.execute(
                    "DELETE FROM pet_access WHERE pet_id = ? AND user_id = ?",
                    (request_row["pet_id"], request_row["from_user_id"])
                )

            parent_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM pet_access WHERE pet_id = ? AND role = 'parent'",
                (request_row["pet_id"],)
            ).fetchone()["cnt"]

            if parent_count <= 1:
                conn.execute(
                    "UPDATE pet SET care_type = 'solo' WHERE id = ?",
                    (request_row["pet_id"],)
                )

        else:
            raise HTTPException(status_code=400, detail="Unsupported request type")

        conn.execute(
            "UPDATE pet_requests SET status = 'accepted', responded_at = ? WHERE id = ?",
            (utc_now(), request_id)
        )

        conn.commit()

    if affected_pet_id is not None:
        await manager.broadcast_pet_state(affected_pet_id)

    return {"status": "accepted"}


@app.post("/requests/{request_id}/decline")
def decline_request(request_id: int, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        request_row = conn.execute(
            "SELECT * FROM pet_requests WHERE id = ?",
            (request_id,)
        ).fetchone()

        if request_row is None:
            raise HTTPException(status_code=404, detail="Request not found")

        if request_row["to_user_id"] != user_id:
            raise HTTPException(status_code=403, detail="This request is not for you")

        if request_row["status"] != "pending":
            raise HTTPException(status_code=400, detail="Request is not pending")

        conn.execute(
            "UPDATE pet_requests SET status = 'declined', responded_at = ? WHERE id = ?",
            (utc_now(), request_id)
        )
        conn.commit()

        return {"status": "declined"}


@app.post("/pets/{pet_id}/unshare-request")
def create_unshare_request(pet_id: int, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        my_access = conn.execute(
            "SELECT id FROM pet_access WHERE pet_id = ? AND user_id = ? AND role = 'parent'",
            (pet_id, user_id)
        ).fetchone()

        if my_access is None:
            raise HTTPException(status_code=403, detail="Only a parent can request unsharing")

        other_parent = conn.execute(
            "SELECT user_id FROM pet_access WHERE pet_id = ? AND role = 'parent' AND user_id != ? ORDER BY id LIMIT 1",
            (pet_id, user_id)
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
            (pet_id, user_id, other_parent["user_id"])
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
            (pet_id, user_id, other_parent["user_id"], 'unshare_request', utc_now())
        )

        conn.commit()
        return {"status": "pending_unshare_created"}


@app.get("/requests/view", response_class=HTMLResponse)
def requests_view():
    return """
    <html>
        <head>
            <title>Requests - Tamagotchi</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: Arial; max-width: 760px; margin: 40px auto;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h1>Запросы</h1>
                <button onclick="window.location.href='/pet/view'">К питомцу</button>
            </div>

            <h2>Входящие</h2>
            <div id="incoming">Загрузка...</div>

            <h2 style="margin-top: 30px;">Исходящие</h2>
            <div id="outgoing">Загрузка...</div>

            <p id="message" style="margin-top: 16px;"></p>

            <script>
                function requestTypeText(type) {
                    if (type === "parent_invite") return "Приглашение в совместное воспитание";
                    if (type === "unshare_request") return "Предложение расторгнуть совместное воспитание";
                    return type;
                }

                function statusText(status) {
                    if (status === "pending") return "ожидает ответа";
                    if (status === "accepted") return "принято";
                    if (status === "declined") return "отклонено";
                    if (status === "cancelled") return "отменено";
                    return status;
                }

                async function loadIncoming() {
                    const token = localStorage.getItem("access_token");
                    const response = await fetch("/requests/incoming", {
                        headers: { "Authorization": "Bearer " + token }
                    });

                    if (!response.ok) {
                        document.getElementById("incoming").innerText = "Не удалось загрузить входящие запросы";
                        return;
                    }

                    const items = await response.json();

                    if (items.length === 0) {
                        document.getElementById("incoming").innerText = "Входящих запросов нет";
                        return;
                    }

                    document.getElementById("incoming").innerHTML = items.map(r => `
                        <div style="border:1px solid #ccc; padding:12px; margin-bottom:10px;">
                            <p><b>${requestTypeText(r.request_type)}</b></p>
                            <p>От: ${r.from_username}</p>
                            <p>Питомец: ${r.pet_name}</p>
                            <p>Статус: ${statusText(r.status)}</p>
                            ${r.status === "pending" ? `
                                <button onclick="acceptRequest(${r.id})">Принять</button>
                                <button onclick="declineRequest(${r.id})">Отклонить</button>
                            ` : ""}
                        </div>
                    `).join("");
                }

                async function loadOutgoing() {
                    const token = localStorage.getItem("access_token");
                    const response = await fetch("/requests/outgoing", {
                        headers: { "Authorization": "Bearer " + token }
                    });

                    if (!response.ok) {
                        document.getElementById("outgoing").innerText = "Не удалось загрузить исходящие запросы";
                        return;
                    }

                    const items = await response.json();

                    if (items.length === 0) {
                        document.getElementById("outgoing").innerText = "Исходящих запросов нет";
                        return;
                    }

                    document.getElementById("outgoing").innerHTML = items.map(r => `
                        <div style="border:1px solid #ccc; padding:12px; margin-bottom:10px;">
                            <p><b>${requestTypeText(r.request_type)}</b></p>
                            <p>Кому: ${r.to_username}</p>
                            <p>Питомец: ${r.pet_name}</p>
                            <p>Статус: ${statusText(r.status)}</p>
                        </div>
                    `).join("");
                }

                async function acceptRequest(requestId) {
                    const token = localStorage.getItem("access_token");
                    const response = await fetch(`/requests/${requestId}/accept`, {
                        method: "POST",
                        headers: { "Authorization": "Bearer " + token }
                    });

                    const data = await response.json();
                    document.getElementById("message").innerText = response.ok ? "Запрос принят" : (data.detail || "Ошибка");
                    loadIncoming();
                    loadOutgoing();
                }

                async function declineRequest(requestId) {
                    const token = localStorage.getItem("access_token");
                    const response = await fetch(`/requests/${requestId}/decline`, {
                        method: "POST",
                        headers: { "Authorization": "Bearer " + token }
                    });

                    const data = await response.json();
                    document.getElementById("message").innerText = response.ok ? "Запрос отклонён" : (data.detail || "Ошибка");
                    loadIncoming();
                    loadOutgoing();
                }

                loadIncoming();
                loadOutgoing();
            </script>
        </body>
    </html>
    """


@app.get("/pets")
def get_my_pets(authorization: str | None = Header(default=None)):
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
            (user_id,)
        ).fetchall()

    return [get_pet_payload_for_user(user_id, row["id"]) for row in rows]


@app.get("/pets/select", response_class=HTMLResponse)
def pets_select_page():
    return """
    <html>
        <head>
            <title>Select Pet - Tamagotchi</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: Arial; max-width: 600px; margin: 40px auto;">
            <h1>Выбор питомца</h1>

            <div id="pets">Загрузка...</div>

            <script>
                async function loadPets() {
                    const token = localStorage.getItem("access_token");

                    if (!token) {
                        window.location.href = "/login";
                        return;
                    }

                    const response = await fetch("/pets", {
                        headers: {
                            "Authorization": "Bearer " + token
                        }
                    });

                    if (!response.ok) {
                        document.getElementById("pets").innerText = "Не удалось загрузить питомцев";
                        return;
                    }

                    const pets = await response.json();

                    if (pets.length === 0) {
                        document.getElementById("pets").innerText = "Питомцы не найдены";
                        return;
                    }

                    document.getElementById("pets").innerHTML = pets.map(p => {
                        const careType = p.care_type === "shared" ? "совместное" : "одиночное";
                        const sharedWith = p.care_type === "shared" && p.shared_with && p.shared_with.length > 0
                            ? `<p>Совместно с: ${p.shared_with.join(", ")}</p>`
                            : "";

                        return `
                            <div style="border:1px solid #ccc; padding:12px; margin-bottom:10px;">
                                <p><b>${p.name}</b></p>
                                <p>Воспитание: ${careType}</p>
                                ${sharedWith}
                                <button onclick="selectPet(${p.id})">Открыть</button>
                            </div>
                        `;
                    }).join("");
                }

                function selectPet(petId) {
                    localStorage.setItem("selected_pet_id", petId);
                    window.location.href = "/pet/view";
                }

                loadPets();
            </script>
        </body>
    </html>
    """


@app.get("/pets/{pet_id}")
def get_pet_by_id(pet_id: int, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    return get_pet_payload_for_user(user_id, pet_id)
