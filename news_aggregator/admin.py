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
    response = templates.TemplateResponse(request, "admin/dashboard.html", {
        "title": "Evening News v2 - Admin",
        "admin_user": admin_user,
        "active_menu": "dashboard"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/sources", response_class=HTMLResponse)
async def admin_sources(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Manage sources."""
    response = templates.TemplateResponse(request, "admin/sources.html", {
        "title": "Управление Источниками",
        "admin_user": admin_user,
        "active_menu": "sources"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/summaries", response_class=HTMLResponse)
async def admin_summaries(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Daily summaries page."""
    response = templates.TemplateResponse(request, "admin/summaries.html", {
        "title": "Дневные Сводки",
        "admin_user": admin_user,
        "active_menu": "summaries"
    })
    return _with_admin_cookie(response, admin_user)




@router.get("/stats", response_class=HTMLResponse)
async def admin_stats(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Statistics page."""
    response = templates.TemplateResponse(request, "admin/stats.html", {
        "title": "Статистика Системы",
        "admin_user": admin_user,
        "active_menu": "stats"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/backup", response_class=HTMLResponse)
async def admin_backup(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Backup and restore page."""
    response = templates.TemplateResponse(request, "admin/backup.html", {
        "title": "Резервные Копии",
        "admin_user": admin_user,
        "active_menu": "backup"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/categories", response_class=HTMLResponse)
async def admin_categories(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Category mapping management page."""
    response = templates.TemplateResponse(request, "admin/categories.html", {
        "title": "Маппинг Категорий",
        "admin_user": admin_user,
        "active_menu": "categories"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Settings page (Telegram + Schedule)."""
    response = templates.TemplateResponse(request, "admin/settings.html", {
        "title": "Настройки",
        "admin_user": admin_user,
        "active_menu": "settings"
    })
    return _with_admin_cookie(response, admin_user)


@router.get("/telegram", response_class=HTMLResponse)
async def admin_telegram(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Telegram settings page (redirects to settings)."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/settings", status_code=302)


@router.get("/schedule", response_class=HTMLResponse)
async def admin_schedule_redirect(request: Request, admin_user: str = Depends(get_current_admin_user)):
    """Schedule page (redirects to settings)."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/settings", status_code=302)
