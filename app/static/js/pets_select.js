async function loadPets() {
    const token = localStorage.getItem("access_token");

    if (!token) {
        window.location.href = "/login";
        return;
    }

    const response = await fetch("/pets", {
        headers: {"Authorization": "Bearer " + token}
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

    document.getElementById("pets").innerHTML = pets.map((p) => {
        const careType = p.care_type === "shared" ? "совместное" : "одиночное";
        const sharedWith = p.care_type === "shared" && p.shared_with && p.shared_with.length > 0
            ? `<p>Совместно с: ${p.shared_with.join(", ")}</p>`
            : "";

        return `
            <div class="card">
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
