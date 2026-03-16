from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])


@router.get("/login", response_class=HTMLResponse)
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


@router.get("/register", response_class=HTMLResponse)
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


@router.get("/pet/view", response_class=HTMLResponse)
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


@router.get("/requests/view", response_class=HTMLResponse)
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


@router.get("/pets/select", response_class=HTMLResponse)
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
