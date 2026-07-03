"""
Discord Query Web App
- 独立网站，用户用 Discord OAuth2 登录
- 管理员可上传 Excel/CSV 表格
- 登录用户可通过关键字搜索表格内容
"""

import os
import io
import json
import time
import secrets
import httpx
import pandas as pd
from pathlib import Path
from fastapi import FastAPI, Request, Response, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# ── 配置 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DATA_FILE = BASE_DIR / "data.json"  # 存储当前表格数据

# Discord OAuth2 配置（需要填入你自己的 Application 信息）
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "YOUR_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
# 重定向 URI — 部署后改成你的域名
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")
# 管理员的 Discord 用户 ID（可上传表格）
ADMIN_DISCORD_ID = os.environ.get("ADMIN_DISCORD_ID", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"

app = FastAPI(title="Discord Query App")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ── 工具函数 ──────────────────────────────────────────
def get_current_user(request: Request) -> dict | None:
    """从 session 获取当前登录用户"""
    return request.session.get("user")


def require_login(request: Request):
    """依赖：必须登录"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def is_admin(user: dict) -> bool:
    """检查是否是管理员"""
    if not ADMIN_DISCORD_ID:
        return False
    return str(user.get("id")) == str(ADMIN_DISCORD_ID)


def load_table_data() -> list[dict]:
    """加载当前上传的表格数据"""
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_table_data(data: list[dict]):
    """保存表格数据"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def search_data(keyword: str, data: list[dict]) -> list[dict]:
    """在表格数据中搜索关键字（不区分大小写）"""
    if not keyword:
        return data
    kw = keyword.lower()
    results = []
    for row in data:
        # 搜索所有字段的值
        if any(kw in str(v).lower() for v in row.values()):
            results.append(row)
    return results


# ── 路由 ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页"""
    user = get_current_user(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "is_admin": is_admin(user) if user else False,
        },
    )


@app.get("/login")
async def login(request: Request):
    """跳转到 Discord OAuth2 登录"""
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "state": state,
    }
    from urllib.parse import urlencode
    url = f"{DISCORD_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = ""):
    """Discord OAuth2 回调"""
    # 验证 state
    saved_state = request.session.get("oauth_state")
    if not state or state != saved_state:
        raise HTTPException(status_code=400, detail="Invalid state")

    # 用 code 换取 access_token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            DISCORD_TOKEN_URL,
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Token error: {token_resp.text}")

        token_data = token_resp.json()
        access_token = token_data["access_token"]

        # 获取用户信息
        user_resp = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get user info")

        user_data = user_resp.json()

    # 保存到 session
    request.session["user"] = {
        "id": user_data["id"],
        "username": user_data.get("username", ""),
        "global_name": user_data.get("global_name", ""),
        "avatar": user_data.get("avatar", ""),
        "email": user_data.get("email", ""),
    }
    request.session.pop("oauth_state", None)

    return RedirectResponse(url="/", status_code=302)


@app.get("/logout")
async def logout(request: Request):
    """登出"""
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@app.get("/search")
async def search(request: Request, q: str = Query("")):
    """搜索接口（需登录）"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)

    data = load_table_data()
    results = search_data(q, data)
    return JSONResponse({
        "keyword": q,
        "total": len(results),
        "results": results,
        "columns": list(data[0].keys()) if data else [],
    })


@app.post("/upload")
async def upload_table(request: Request, file: UploadFile = File(...)):
    """上传表格（仅管理员）"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)
    if not is_admin(user):
        return JSONResponse({"error": "无权限，仅管理员可上传"}, status_code=403)

    # 读取文件
    content = await file.read()
    filename = file.filename.lower()

    try:
        if filename.endswith(".csv"):
            # 尝试多种编码
            for enc in ["utf-8", "gbk", "gb2312", "latin1"]:
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc)
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            else:
                return JSONResponse({"error": "CSV 编码无法识别"}, status_code=400)
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            return JSONResponse({"error": "仅支持 .xlsx, .xls, .csv 文件"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"解析失败: {str(e)}"}, status_code=400)

    # 转换为 dict 列表，处理 NaN
    df = df.fillna("")
    records = df.to_dict(orient="records")

    # 保存
    save_table_data(records)

    # 同时保存原始文件备份
    saved_path = UPLOAD_DIR / file.filename
    with open(saved_path, "wb") as f:
        f.write(content)

    return JSONResponse({
        "message": "上传成功",
        "rows": len(records),
        "columns": list(df.columns),
        "filename": file.filename,
    })


@app.get("/table/info")
async def table_info(request: Request):
    """获取当前表格信息（需登录）"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)
    data = load_table_data()
    return JSONResponse({
        "total_rows": len(data),
        "columns": list(data[0].keys()) if data else [],
    })


@app.get("/avatar/{user_id}/{avatar_hash}")
async def avatar(request: Request, user_id: str, avatar_hash: str):
    """代理 Discord 头像（避免前端直连被墙）"""
    url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return Response(content=resp.content, media_type="image/png")


# ── 启动 ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
