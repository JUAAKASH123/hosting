import os
import time
import threading
import json
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from typing import Optional

from fastapi import FastAPI, Request, Header, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
import starlette

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials as firebase_credentials
from email_utils import send_login_email

# ─────────────────────────────────────────────────────────────────────────
# SHARED-HOSTING BUILD (browser-only AI)
# All pose/hand/garment AI runs in the visitor's browser (MediaPipe Tasks
# Vision, WASM). This backend serves pages, auth, the garment list and
# static files. Garment PNGs are pre-processed offline (preprocess_garments.py).
# ─────────────────────────────────────────────────────────────────────────

app = FastAPI()

FIREBASE_CRED_PATH = os.environ.get("FIREBASE_CREDENTIALS_PATH")
if not FIREBASE_CRED_PATH:
    raise RuntimeError("FIREBASE_CREDENTIALS_PATH env var not set")

# Guard against "app already initialized" (--reload, double import, preload).
if not firebase_admin._apps:
    try:
        firebase_admin.initialize_app(firebase_credentials.Certificate(FIREBASE_CRED_PATH))
    except FileNotFoundError:
        raise RuntimeError(
            f"FIREBASE_CREDENTIALS_PATH is set to '{FIREBASE_CRED_PATH}' but no file "
            f"exists there. Check the path is correct and the file was actually "
            f"deployed alongside the app."
        )
    except ValueError as e:
        raise RuntimeError(
            f"FIREBASE_CREDENTIALS_PATH points to a file that isn't a valid Firebase "
            f"service-account key ({e}). Re-download it from Firebase Console → "
            f"Project Settings → Service Accounts if it may be corrupted or truncated."
        )

REVOCATION_RECHECK_INTERVAL = 120  # seconds
_uid_revocation_checked = {}
_uid_revocation_lock = threading.Lock()

_token_verify_cache = {}
_token_verify_lock = threading.Lock()
TOKEN_VERIFY_CACHE_TTL = 60  # seconds


async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1]

    now = time.time()
    with _token_verify_lock:
        cached = _token_verify_cache.get(token)
        if cached and now < cached[1]:
            decoded = cached[0]
        else:
            decoded = None

    if decoded is None:
        try:
            decoded = await run_in_threadpool(firebase_auth.verify_id_token, token)
        except firebase_auth.ExpiredIdTokenError:
            raise HTTPException(401, "Session expired, please log in again")
        except Exception:
            raise HTTPException(401, "Invalid or expired token")

        with _token_verify_lock:
            if len(_token_verify_cache) > 5000:
                _token_verify_cache.clear()
            _token_verify_cache[token] = (decoded, now + TOKEN_VERIFY_CACHE_TTL)

    uid = decoded["uid"]
    with _uid_revocation_lock:
        last_checked = _uid_revocation_checked.get(uid, 0)
        need_check = (now - last_checked) > REVOCATION_RECHECK_INTERVAL
        if need_check:
            _uid_revocation_checked[uid] = now

    if need_check:
        try:
            await run_in_threadpool(firebase_auth.verify_id_token, token, check_revoked=True)
        except firebase_auth.RevokedIdTokenError:
            with _uid_revocation_lock:
                _uid_revocation_checked.pop(uid, None)
            raise HTTPException(401, "Session revoked, please log in again")
        except firebase_auth.ExpiredIdTokenError:
            raise HTTPException(401, "Session expired, please log in again")
        except Exception:
            pass

    return decoded


_origins_env = os.environ.get("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if _origins_env.strip() == "*" else [o.strip() for o in _origins_env.split(",")]

if ALLOWED_ORIGINS == ["*"]:
    print(
        "\n⚠️  ALLOWED_ORIGINS is not set — CORS is wide open (allow_origins=['*']).\n"
        "    Fine for local dev/testing. Before a real deploy, set it explicitly, e.g.\n"
        "    ALLOWED_ORIGINS=\"https://yourdomain.com\"\n"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Create assets/ if missing so StaticFiles doesn't crash the app at import.
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
if not os.path.isdir(ASSETS_DIR):
    os.makedirs(ASSETS_DIR, exist_ok=True)
    print(
        f"\n⚠️  '{ASSETS_DIR}' did not exist and was created empty. The app will "
        f"start, but /clothes will return no garments and /assets will serve "
        f"nothing until you upload assets/he/ (see preprocess_garments.py).\n"
    )
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

ASSET_PATH = os.path.join(BASE_DIR, "assets", "he")

# Telemetry log defaults to /tmp (many hosts mount the app dir read-only).
TELEMETRY_LOG_PATH = os.environ.get(
    "TELEMETRY_LOG_PATH",
    os.path.join("/tmp", "virtufit_telemetry.log"),
)
_telemetry_lock = threading.Lock()

_telemetry_logger = logging.getLogger("virtufit.telemetry")
_telemetry_logger.setLevel(logging.INFO)
_telemetry_logger.propagate = False

_telemetry_enabled = True
try:
    _telemetry_handler = RotatingFileHandler(
        TELEMETRY_LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    _telemetry_handler.setFormatter(logging.Formatter("%(message)s"))
    _telemetry_logger.addHandler(_telemetry_handler)
except OSError as e:
    print(
        f"\n⚠️  Could not open telemetry log at '{TELEMETRY_LOG_PATH}' ({e}). "
        f"Telemetry will be disabled for this run. Set TELEMETRY_LOG_PATH to a "
        f"writable location to re-enable it.\n"
    )
    _telemetry_logger.addHandler(logging.NullHandler())
    _telemetry_enabled = False

SUPPORTED_EXTS = (".png", ".jpg", ".jpeg", ".webp")

RATE_LIMIT_WINDOW = 1.0
RATE_LIMIT_MAX_REQ = 20

_rate_state = {}
_rate_lock = threading.Lock()


def _check_rate_limit(key: str, window: float = RATE_LIMIT_WINDOW,
                      max_req: int = RATE_LIMIT_MAX_REQ) -> bool:
    now = time.time()
    with _rate_lock:
        if len(_rate_state) > 2000:
            for k in [k for k, v in _rate_state.items()
                      if not v or now - v[-1] > window * 5]:
                _rate_state.pop(k, None)

        bucket = _rate_state.setdefault(key, deque())
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= max_req:
            return False
        bucket.append(now)
        return True


_starlette_new = tuple(int(x) for x in starlette.__version__.split(".")[:2]) >= (0, 36)


def _render(request: Request, name: str, context: dict = {}):
    if _starlette_new:
        return templates.TemplateResponse(request=request, name=name, context=context)
    return templates.TemplateResponse(name, {"request": request, **context})


@app.get("/")
def homepage(request: Request):
    return _render(request, "home.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "telemetry_enabled": _telemetry_enabled}


@app.get("/tryon-browser")
def index_browser(request: Request):
    return _render(request, "index.html")


@app.get("/clothes")
def get_clothes():
    clothes = []
    if os.path.exists(ASSET_PATH):
        clothes = sorted([
            f for f in os.listdir(ASSET_PATH)
            if f.lower().endswith(SUPPORTED_EXTS)
        ])
    return JSONResponse({"clothes": clothes, "count": len(clothes)})


TELEMETRY_RATE_LIMIT_WINDOW = 60.0
TELEMETRY_RATE_LIMIT_MAX_REQ = 4


@app.post("/telemetry")
async def telemetry(request: Request, user=Depends(get_current_user)):
    if not _check_rate_limit(f"telemetry:{user['uid']}",
                             window=TELEMETRY_RATE_LIMIT_WINDOW,
                             max_req=TELEMETRY_RATE_LIMIT_MAX_REQ):
        return Response(status_code=429, content=b"Too many requests")

    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=400)

    entry = {
        "ts": time.time(),
        "uid": user["uid"],
        "mode": payload.get("mode"),
        "fps_avg": payload.get("fps_avg"),
        "fps_min": payload.get("fps_min"),
        "device": payload.get("device"),
        "gpu_delegate": payload.get("gpu_delegate"),
    }

    with _telemetry_lock:
        _telemetry_logger.info(json.dumps(entry))

    return {"ok": True}


@app.get("/howitworks")
def howitworks(request: Request):
    return _render(request, "howitworks.html")


@app.get("/about")
def about(request: Request):
    return _render(request, "about.html")


@app.get("/feature")
def feature(request: Request):
    return _render(request, "feature.html")


@app.get("/home")
def home_alias(request: Request):
    return _render(request, "home.html")


@app.get("/login.html", response_class=HTMLResponse)
async def login(request: Request):
    return _render(request, "login.html")


def _send_login_email_safe(name: str, email: str):
    """Runs in its own daemon thread. Never raises, never blocks a request."""
    try:
        send_login_email(name, email)
    except Exception as e:
        print("LOGIN EMAIL ERROR:", repr(e))


@app.post("/api/login-success")
async def login_success(
    authorization: str = Header(...),
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1]

    try:
        decoded = await run_in_threadpool(
            firebase_auth.verify_id_token, token, clock_skew_seconds=10
        )
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    try:
        uid = decoded["uid"]

        if not _check_rate_limit(f"login-success:{uid}"):
            raise HTTPException(status_code=429, detail="Too many requests")

        email = decoded.get("email")
        name = decoded.get("name", "User")

        # Sent from a standalone thread instead of BackgroundTasks:
        # Starlette holds the response/connection open until background
        # tasks finish, so a slow SMTP server was delaying the browser's
        # next request (the redirect to /tryon-browser) by a minute or more.
        if email and decoded.get("email_verified"):
            threading.Thread(
                target=_send_login_email_safe, args=(name, email), daemon=True
            ).start()

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        print("LOGIN ERROR:", repr(e))
        raise HTTPException(status_code=500, detail="Login failed, please try again")