"""
Yardım ve SSS sayfaları — kimlik doğrulama gerektirmez.
GET /help
GET /faq
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from templates_config import templates

router = APIRouter(tags=["help"])


@router.get("/help", response_class=HTMLResponse, name="help_index")
async def help_index(request: Request):
    return templates.TemplateResponse(
        "help/index.html",
        {"request": request, "current_user": None, "page_title": "Yardım Merkezi"},
    )


@router.get("/faq", response_class=HTMLResponse, name="faq")
async def faq(request: Request):
    return templates.TemplateResponse(
        "help/faq.html",
        {"request": request, "current_user": None, "page_title": "Sık Sorulan Sorular"},
    )
