const form = document.getElementById("login-form");
const result = document.getElementById("result");

form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    const response = await fetch("/auth/login", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
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
