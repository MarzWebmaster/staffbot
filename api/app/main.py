from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os

from app.config import get_settings
from app.database import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        print("[StaffBot API] Database tables initialized")
    except Exception as e:
        print(f"[StaffBot API] DB init warning: {e}")
    yield
    print("[StaffBot API] Shutting down")


app = FastAPI(
    title="StaffBot.my API",
    version="1.0.0",
    description="Digital Employee as a Service (DEaaS) — Backend API",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")



@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    path = os.path.join(os.path.dirname(__file__), "static", "sitemap.xml")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/xml")
    return {"error": "Not found"}


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    path = os.path.join(os.path.dirname(__file__), "static", "robots.txt")
    if os.path.exists(path):
        return FileResponse(path, media_type="text/plain")
    return {"error": "Not found"}


@app.get("/")

async def root():
    landing = os.path.join(os.path.dirname(__file__), "static", "landing.html")
    if os.path.exists(landing):
        return FileResponse(landing, media_type="text/html")
    return RedirectResponse(url="/admin/login.html")


@app.get("/policy-usage")
async def policy_usage_page():
    page = os.path.join(os.path.dirname(__file__), "static", "policy-usage.html")
    if os.path.exists(page):
        return FileResponse(page)
    return {"error": "Page not found"}


@app.get("/customer/{page}")
async def customer_page(page: str):
    import re
    if not re.match(r"^[a-zA-Z0-9_.-]+$", page):
        return RedirectResponse(url="/customer/login.html")
    file_path = os.path.join(static_dir, "customer", page)
    real_path = os.path.realpath(file_path)
    customer_dir = os.path.realpath(os.path.join(static_dir, "customer"))
    if not real_path.startswith(customer_dir):
        return RedirectResponse(url="/customer/login.html")
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    login_path = os.path.join(static_dir, "customer", "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return RedirectResponse(url="/admin/login.html")


@app.get("/admin/{page}")
async def admin_page(page: str):
    import re
    if not re.match(r"^[a-zA-Z0-9_.-]+$", page):
        return RedirectResponse(url="/admin/login.html")
    file_path = os.path.join(static_dir, "admin", page)
    real_path = os.path.realpath(file_path)
    admin_dir = os.path.realpath(os.path.join(static_dir, "admin"))
    if not real_path.startswith(admin_dir):
        return RedirectResponse(url="/admin/login.html")
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    return RedirectResponse(url="/admin/login.html")


@app.get("/admin")
async def admin_root():
    return RedirectResponse(url="/admin/login.html")


@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0", "service": "StaffBot.my API"}


# Import and register routers
from app.routers import auth, clients, subscriptions, containers, webhooks, notifications
from app.routers.billing import router as billing_router
from app.routers.llm_providers import router as user_llm_providers_router
from app.routers.admin import dashboard, packages, users, settings as admin_settings, policy as admin_policy
from app.routers.admin.llm_providers import router as admin_llm_providers_router
from app.routers.affiliates import router as user_affiliates_router
from app.routers.admin.affiliates import router as admin_affiliates_router
from app.routers.admin.payments import router as admin_payments_router
from app.routers.admin.token_topups import router as admin_topups_router

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(billing_router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(clients.router, prefix="/api/v1/clients", tags=["Clients"])
app.include_router(subscriptions.router, prefix="/api/v1/subscriptions", tags=["Subscriptions"])
app.include_router(containers.router, prefix="/api/v1/containers", tags=["Containers"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])
app.include_router(dashboard.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(packages.router, prefix="/api/v1/admin/packages", tags=["Admin Packages"])
app.include_router(users.router, prefix="/api/v1/admin/users", tags=["Admin Users"])
app.include_router(admin_settings.router, prefix="/api/v1/admin/settings", tags=["Admin Settings"])
app.include_router(admin_llm_providers_router, prefix="/api/v1/admin/providers", tags=["Admin LLM Providers"])
app.include_router(user_llm_providers_router, prefix="/api/v1/providers", tags=["LLM Providers"])
app.include_router(admin_affiliates_router, prefix="/api/v1/admin/affiliates", tags=["Admin Affiliates"])
app.include_router(admin_payments_router, prefix="/api/v1/admin", tags=["Admin Payments"])
app.include_router(admin_topups_router, prefix="/api/v1/admin/topup-packages", tags=["Admin Top-Up"])
app.include_router(admin_policy.router, prefix="/api/v1/admin/policy", tags=["Admin Policy"])
app.include_router(user_affiliates_router, prefix="/api/v1/affiliates", tags=["Affiliates"])
