"""Admin interface routes."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .auth import get_current_admin_user

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Admin dashboard."""
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "title": "RSS Summarizer v2 - Admin",
        "admin_user": admin_user,
        "active_menu": "dashboard"
    })


@router.get("/sources", response_class=HTMLResponse)
async def admin_sources(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Manage sources."""
    return templates.TemplateResponse("admin/sources.html", {
        "request": request,
        "title": "Управление Источниками",
        "admin_user": admin_user,
        "active_menu": "sources"
    })


@router.get("/summaries", response_class=HTMLResponse)
async def admin_summaries(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Daily summaries page."""
    return templates.TemplateResponse("admin/summaries.html", {
        "request": request,
        "title": "Дневные Сводки",
        "admin_user": admin_user,
        "active_menu": "summaries"
    })


@router.get("/schedule", response_class=HTMLResponse)
async def admin_schedule(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Schedule settings page."""
    return templates.TemplateResponse("admin/schedule.html", {
        "request": request,
        "title": "Расписание Задач",
        "admin_user": admin_user,
        "active_menu": "schedule"
    })


@router.get("/stats", response_class=HTMLResponse)
async def admin_stats(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Statistics page."""
    return templates.TemplateResponse("admin/stats.html", {
        "request": request,
        "title": "Статистика Системы",
        "admin_user": admin_user,
        "active_menu": "stats"
    })


@router.get("/backup", response_class=HTMLResponse)
async def admin_backup(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Backup and restore page."""
    return templates.TemplateResponse("admin/backup.html", {
        "request": request,
        "title": "Резервные Копии",
        "admin_user": admin_user,
        "active_menu": "backup"
    })


@router.get("/categories", response_class=HTMLResponse)
async def admin_categories(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Category mapping management page."""
    return templates.TemplateResponse("admin/categories.html", {
        "request": request,
        "title": "Маппинг Категорий",
        "admin_user": admin_user,
        "active_menu": "categories"
    })
