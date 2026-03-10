import asyncio
import random
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from auth import hash_password, create_access_token, verify_password, decode_access_token
from pydantic import BaseModel

DB_PATH = "/opt/tamagotchi/tamagotchi.db"
TICK_SECONDS = 60
SATIETY_ALERT_THRESHOLD = 30

app = FastAPI(title="Tamagotchi Server")

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
    user_id = decode_access_token(token)

    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user_id

def init_db():
    with closing(get_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pet (
                id INTEGER PRIMARY KEY,
                name TEXT,
                satiety INTEGER,
                mood INTEGER,
                energy INTEGER,
                sleeping INTEGER,
                satiety_alert_30_sent INTEGER,
                updated_at TEXT
            )
            """
        )

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

        pet = conn.execute("SELECT * FROM pet WHERE id = 1").fetchone()

        if pet is None:
            conn.execute(
                """
                INSERT INTO pet (
                    id, name, satiety, mood, energy, sleeping,
                    satiety_alert_30_sent, updated_at
                )
                VALUES (1, 'Muffin', 80, 80, 70, 0, 0, ?)
                """,
                (utc_now(),)
            )

        conn.commit()


def get_pet():
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT * FROM pet WHERE id = 1").fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Pet not found")
        return dict(row)


def get_pet_by_owner_id(owner_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM pet WHERE owner_id = ?",
            (owner_id,)
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Pet not found")

        return dict(row)


def save_pet(pet):
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
                owner_id = ?
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
                pet["owner_id"],
                pet["id"],
            ),
        )
        conn.commit()


def update_pet_state():
    pet = get_pet()

    if pet["sleeping"]:
        pet["energy"] = clamp(pet["energy"] + random.randint(1, 3))
        pet["satiety"] = clamp(pet["satiety"] - random.randint(0, 1))
        pet["mood"] = clamp(pet["mood"] - random.randint(0, 1))
    else:
        pet["satiety"] = clamp(pet["satiety"] - random.randint(1, 3))
        pet["mood"] = clamp(pet["mood"] - random.randint(0, 2))
        pet["energy"] = clamp(pet["energy"] - random.randint(0, 2))

    if pet["satiety"] <= SATIETY_ALERT_THRESHOLD:
        pet["satiety_alert_30_sent"] = 1
    else:
        pet["satiety_alert_30_sent"] = 0

    pet["updated_at"] = utc_now()
    save_pet(pet)


async def pet_loop():
    while True:
        await asyncio.sleep(TICK_SECONDS)
        update_pet_state()


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(pet_loop())


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/pet")
def read_pet():
    return get_pet()



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
                <button onclick="window.location.href='/pets/select'">Сменить питомца</button>
		<button onclick="logout()">Выйти</button>
            </div>

            <p id="user" style="color:gray;"></p>

            <div id="pet">Загрузка...</div>

            <div style="margin-top: 20px; display: flex; gap: 10px; flex-wrap: wrap;">
                <button onclick="action('/pet/feed')">Покормить</button>
                <button onclick="action('/pet/play')">Поиграть</button>
                <button onclick="action('/pet/sleep')">Уложить спать</button>
                <button onclick="action('/pet/wake')">Разбудить</button>
            </div>

            <p id="message" style="margin-top: 16px;"></p>

            <script>

                function logout() {
                    localStorage.removeItem("access_token");
                    window.location.href = "/login";
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

async function loadPet() {
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

    const response = await fetch("/pets/" + petId, {
        headers: {
            "Authorization": "Bearer " + token
        }
    });

    if (!response.ok) {
        document.getElementById("pet").innerText = "Не удалось загрузить питомца";
        return;
    }

    const pet = await response.json();
    const sleepingText = pet.sleeping ? "Да 😴" : "Нет 🙂";
    const roleText = pet.role === "parent" ? "родитель" : pet.role;
    const careTypeText = pet.care_type === "shared" ? "совместное" : "одиночное";
    const updatedText = new Date(pet.updated_at).toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
    });

    document.getElementById("pet").innerHTML = `
        <p><b>Имя:</b> ${pet.name}</p>
        <p><b>Роль:</b> ${roleText}</p>
        <p><b>Воспитание:</b> ${careTypeText}</p>
        <p><b>Сытость:</b> ${pet.satiety}</p>
        <p><b>Настроение:</b> ${pet.mood}</p>
        <p><b>Энергия:</b> ${pet.energy}</p>
        <p><b>Спит:</b> ${sleepingText}</p>
        <p><b>Обновлён:</b> ${updatedText}</p>
    `;
}

                async function action(url) {
                    const token = localStorage.getItem("access_token");

                    if (!token) {
                        window.location.href = "/login";
                        return;
                    }

                    const response = await fetch(url, {
                        method: "POST",
                        headers: {
                            "Authorization": "Bearer " + token
                        }
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        document.getElementById("message").innerText = data.detail || "Ошибка действия";
                        return;
                    }

                    document.getElementById("message").innerText = "Действие выполнено";
                    loadPet();
                }

                loadUser();
                loadPet();


		setInterval(loadPet, 1000)
            </script>
        </body>
    </html>
    """


@app.post("/pet/feed")
def feed_pet(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    pet = get_pet_by_owner_id(user_id)

    pet["satiety"] = clamp(pet["satiety"] + random.randint(8, 15))
    pet["mood"] = clamp(pet["mood"] + random.randint(1, 4))
    pet["updated_at"] = utc_now()

    save_pet(pet)
    return pet

@app.post("/pet/play")
def play_with_pet(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    pet = get_pet_by_owner_id(user_id)

    if pet["sleeping"]:
        raise HTTPException(status_code=400, detail="Pet is sleeping")

    pet["mood"] = clamp(pet["mood"] + random.randint(6, 12))
    pet["energy"] = clamp(pet["energy"] - random.randint(4, 8))
    pet["satiety"] = clamp(pet["satiety"] - random.randint(2, 5))
    pet["updated_at"] = utc_now()

    save_pet(pet)
    return pet

@app.post("/pet/sleep")
def put_pet_to_sleep(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    pet = get_pet_by_owner_id(user_id)

    pet["sleeping"] = 1
    pet["updated_at"] = utc_now()

    save_pet(pet)
    return pet

@app.post("/pet/wake")
def wake_pet(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)
    pet = get_pet_by_owner_id(user_id)

    pet["sleeping"] = 0
    pet["updated_at"] = utc_now()

    save_pet(pet)
    return pet

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
            "SELECT * FROM pet WHERE owner_id = ?",
            (user_id,)
        ).fetchone()

        if pet is None:
            raise HTTPException(status_code=404, detail="Pet not found")

        return dict(pet)

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
def invite_user(data: InviteRequest, authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:

        # находим питомца владельца
        pet = conn.execute(
            "SELECT id FROM pet WHERE owner_id = ?",
            (user_id,)
        ).fetchone()

        if pet is None:
            raise HTTPException(status_code=404, detail="Pet not found")

        pet_id = pet["id"]

        # ищем пользователя которого приглашаем
        target_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (data.username,)
        ).fetchone()

        if target_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        target_user_id = target_user["id"]

        # проверяем нет ли уже доступа
        existing = conn.execute(
            "SELECT id FROM pet_access WHERE pet_id = ? AND user_id = ?",
            (pet_id, target_user_id)
        ).fetchone()

        if existing:
            raise HTTPException(status_code=400, detail="User already has access")

        # добавляем доступ
        conn.execute(
            """
            INSERT INTO pet_access (pet_id, user_id, role, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                pet_id,
                target_user_id,
                "parent",
                utc_now()
            )
        )

        conn.execute(
            """
            UPDATE pet
            SET care_type = 'shared'
            WHERE id = ?
            """,
            (pet_id,)
        )

        conn.commit()

        return {"status": "invited"}


@app.get("/pets")
def get_my_pets(authorization: str | None = Header(default=None)):
    user_id = get_user_id_from_auth_header(authorization)

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT
                pet.id,
                pet.name,
                pet.satiety,
                pet.mood,
                pet.energy,
                pet.sleeping,
                pet.satiety_alert_30_sent,
                pet.updated_at,
                pet.owner_id,
                pet.care_type,
                pet_access.role
            FROM pet
            JOIN pet_access ON pet.id = pet_access.pet_id
            WHERE pet_access.user_id = ?
            ORDER BY pet.id
            """,
            (user_id,)
        ).fetchall()

        return [dict(row) for row in rows]

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

                    document.getElementById("pets").innerHTML = pets.map(p => `
                        <div style="border:1px solid #ccc; padding:12px; margin-bottom:10px;">
                            <p><b>${p.name}</b></p>
                            <p>Роль: ${p.role === "parent" ? "родитель" : p.role}</p>
                            <p>Воспитание: ${p.care_type === "shared" ? "совместное" : "одиночное"}</p>
                            <button onclick="selectPet(${p.id})">Открыть</button>
                        </div>
                    `).join("");
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

        data = dict(pet)
        data["role"] = access["role"]

        return data

