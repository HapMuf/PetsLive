const form = document.getElementById("register-form");
const result = document.getElementById("result");

form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    const response = await fetch("/auth/register", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
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
