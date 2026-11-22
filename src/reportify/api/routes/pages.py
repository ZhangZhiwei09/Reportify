"""Admin console pages (07 §7).

The server renders the shell only; every piece of data arrives through the JSON
API and is written with ``textContent``. That keeps user content out of the HTML
pipeline and lets CSP stay strict.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(include_in_schema=False)

PAGES: dict[str, str] = {
    "analysis": "分析工作台",
    "reports": "报告库",
    "scheduler": "定时任务",
    "sources": "数据源",
    "metadata": "字段元数据",
    "mcp": "MCP Servers",
    "skills": "Skills",
    "templates": "Report Templates",
}


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _render(request: Request, page: str) -> HTMLResponse:
    return _templates(request).TemplateResponse(
        request,
        f"{page}.html",
        {"active": page, "title": PAGES[page]},
    )


@router.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse("/analysis", status_code=302)


@router.get("/analysis", response_class=HTMLResponse)
async def analysis_page(request: Request) -> HTMLResponse:
    return _render(request, "analysis")


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request) -> HTMLResponse:
    return _render(request, "reports")


@router.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request) -> HTMLResponse:
    return _render(request, "scheduler")


@router.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request) -> HTMLResponse:
    return _render(request, "sources")


@router.get("/metadata", response_class=HTMLResponse)
async def metadata_page(request: Request) -> HTMLResponse:
    return _render(request, "metadata")


@router.get("/mcp", response_class=HTMLResponse)
async def mcp_page(request: Request) -> HTMLResponse:
    return _render(request, "mcp")


@router.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    return _render(request, "skills")


@router.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request) -> HTMLResponse:
    return _render(request, "templates")
