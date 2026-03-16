from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {})


@router.get("/pet/view", response_class=HTMLResponse)
def pet_view(request: Request):
    return templates.TemplateResponse(request, "pet_view.html", {})


@router.get("/requests/view", response_class=HTMLResponse)
def requests_view(request: Request):
    return templates.TemplateResponse(request, "requests_view.html", {})


@router.get("/pets/select", response_class=HTMLResponse)
def pets_select_page(request: Request):
    return templates.TemplateResponse(request, "pets_select.html", {})
