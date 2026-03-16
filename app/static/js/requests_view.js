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
        headers: {"Authorization": "Bearer " + token}
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
        <div class="card">
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
        headers: {"Authorization": "Bearer " + token}
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
        <div class="card">
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
        headers: {"Authorization": "Bearer " + token}
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
        headers: {"Authorization": "Bearer " + token}
    });

    const data = await response.json();
    document.getElementById("message").innerText = response.ok ? "Запрос отклонён" : (data.detail || "Ошибка");
    loadIncoming();
    loadOutgoing();
}

loadIncoming();
loadOutgoing();
