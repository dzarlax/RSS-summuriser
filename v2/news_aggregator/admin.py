"""Admin interface routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Admin dashboard."""
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "title": "RSS Summarizer v2 - Admin"
    })


@router.get("/sources", response_class=HTMLResponse)
async def admin_sources(request: Request):
    """Manage sources."""
    return templates.TemplateResponse("admin/sources.html", {
        "request": request,
        "title": "Управление Источниками"
    })



@router.get("/summaries", response_class=HTMLResponse)
async def admin_summaries(request: Request):
    """Daily summaries page."""
    return templates.TemplateResponse("admin/summaries.html", {
        "request": request,
        "title": "Дневные Сводки"
    })


@router.get("/schedule", response_class=HTMLResponse)
async def admin_schedule(request: Request):
    """Schedule settings page."""
    return templates.TemplateResponse("admin/schedule.html", {
        "request": request,
        "title": "Расписание Задач"
    })


@router.get("/stats", response_class=HTMLResponse)
async def admin_stats(request: Request):
    """Statistics page."""
    return templates.TemplateResponse("admin/stats.html", {
        "request": request,
        "title": "Статистика Системы"
    })


@router.get("/backup", response_class=HTMLResponse)
async def admin_backup(request: Request):
    """Backup and restore page."""
    return templates.TemplateResponse("admin/backup.html", {
        "request": request,
        "title": "Резервные Копии"
    })