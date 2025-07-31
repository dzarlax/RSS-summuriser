"""Public interface routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/news", response_class=HTMLResponse)
async def public_news_feed(request: Request):
    """Public news feed."""
    return templates.TemplateResponse("public/feed.html", {
        "request": request,
        "title": "Новости"
    })