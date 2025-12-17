"""Admin interface routes."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .auth import get_current_admin_user
from .security import create_jwt_token
from .config import settings

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


def _with_admin_cookie(response, username: str):
    """Set admin JWT cookie for API calls from the admin UI."""
    token = create_jwt_token(username)
    response.set_cookie(
        "admin_token",
        token,
        httponly=True,
        secure=not settings.development,
        samesite="lax",
        max_age=24 * 3600,
        path="/",
    )
    return response


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Admin dashboard."""
    response = templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "title": "RSS Summarizer v2 - Admin",
        "admin_user": admin_user,
        "active_menu": "dashboard"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/sources", response_class=HTMLResponse)
async def admin_sources(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Manage sources."""
    response = templates.TemplateResponse("admin/sources.html", {
        "request": request,
        "title": "Управление Источниками",
        "admin_user": admin_user,
        "active_menu": "sources"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/summaries", response_class=HTMLResponse)
async def admin_summaries(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Daily summaries page."""
    response = templates.TemplateResponse("admin/summaries.html", {
        "request": request,
        "title": "Дневные Сводки",
        "admin_user": admin_user,
        "active_menu": "summaries"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/schedule", response_class=HTMLResponse)
async def admin_schedule(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Schedule settings page."""
    response = templates.TemplateResponse("admin/schedule.html", {
        "request": request,
        "title": "Расписание Задач",
        "admin_user": admin_user,
        "active_menu": "schedule"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/stats", response_class=HTMLResponse)
async def admin_stats(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Statistics page."""
    response = templates.TemplateResponse("admin/stats.html", {
        "request": request,
        "title": "Статистика Системы",
        "admin_user": admin_user,
        "active_menu": "stats"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/backup", response_class=HTMLResponse)
async def admin_backup(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Backup and restore page."""
    response = templates.TemplateResponse("admin/backup.html", {
        "request": request,
        "title": "Резервные Копии",
        "admin_user": admin_user,
        "active_menu": "backup"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/categories", response_class=HTMLResponse)
async def admin_categories(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Category mapping management page."""
    response = templates.TemplateResponse("admin/categories.html", {
        "request": request,
        "title": "Маппинг Категорий",
        "admin_user": admin_user,
        "active_menu": "categories"
    })
    return _with_admin_cookie(response, admin_user)
