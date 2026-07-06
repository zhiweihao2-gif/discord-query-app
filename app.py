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
# 黑名單 Discord ID（逗號分隔）
BLOCKED_USERS = set(
    uid.strip() for uid in os.environ.get("BLOCKED_USERS", "").split(",") if uid.strip()
)
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


# ── 資料快取（記憶體，不怕重新部署清零）──────────────
_cache_data: list[dict] = []
_cache_time: float = 0
CACHE_TTL = 60  # 60 秒內不重複拉 Google Sheets

SHEETS_URL = os.environ.get("GOOGLE_SHEETS_URL", "")


async def refresh_from_sheets() -> int:
    """從 Google Sheets 拉取最新數據，返回筆數"""
    global _cache_data, _cache_time
    url = SHEETS_URL or load_sheets_url()
    if not url:
        print("⚠️ refresh_from_sheets: 無 URL")
        return len(_cache_data)
    print(f"🔄 正在從 Sheets 拉取: {url[:80]}...")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            print(f"   HTTP {resp.status_code}, 長度={len(resp.text)}")
            if resp.status_code != 200 or not resp.text.strip():
                print(f"   ❌ 無效回應")
                return len(_cache_data)
            df = pd.read_csv(io.StringIO(resp.text))
            df = df.fillna("")
            _cache_data = df.to_dict(orient="records")
            _cache_time = __import__("time").time()
            print(f"   ✅ 成功: {len(_cache_data)} 條, 列: {list(df.columns)}")
    except Exception as e:
        print(f"   ❌ 例外: {e}")
    return len(_cache_data)


async def get_cached_data(force: bool = False) -> list[dict]:
    """取得資料：自動從 Sheets 刷新（60秒緩存）"""
    global _cache_data, _cache_time
    if force:
        return _cache_data
    # 有 GOOGLE_SHEETS_URL 時，過期自動刷新
    has_url = bool(SHEETS_URL or load_sheets_url())
    if has_url and (__import__("time").time() - _cache_time > CACHE_TTL or not _cache_data):
        await refresh_from_sheets()
    return _cache_data


def set_data(data: list[dict]):
    """設置快取資料（上傳/Sync 時使用）"""
    global _cache_data, _cache_time
    _cache_data = data
    _cache_time = __import__("time").time()
    _save_to_disk(data)  # 備份到硬碟


def _save_to_disk(data: list[dict]):
    """寫入 data.json（備份用）"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


SHEETS_CONFIG_FILE = BASE_DIR / "sheets_config.json"


def load_sheets_url() -> str:
    """加载已保存的 Google Sheets URL"""
    if SHEETS_CONFIG_FILE.exists():
        with open(SHEETS_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("url", "")
    return ""


def save_sheets_url(url: str):
    with open(SHEETS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"url": url}, f)


def find_column(columns: list, *keywords: str) -> str | None:
    """在列名中查找匹配關鍵字的列（關鍵字優先級 > 欄位順序）"""
    for kw in keywords:
        kw_lower = kw.lower()
        for col in columns:
            if kw_lower in col.lower():
                return col
    return None


def search_data(
    data: list[dict],
    player_id: str = "",
    work: str = "",
    keyword: str = "",
) -> list[dict]:
    """多条件搜索表格数据"""
    if not data:
        return []
    columns = list(data[0].keys())

    # 自动识别"玩家ID"列和"作品"列
    id_col = find_column(columns, "玩家id", "player", "id", "用戶id", "用户id")
    work_col = find_column(columns, "作品", "work", "項目", "项目")

    results = data
    if player_id and id_col:
        pid = player_id.lower()
        results = [r for r in results if pid in str(r.get(id_col, "")).lower()]
    if work and work_col:
        results = [r for r in results if str(r.get(work_col, "")) == work]
    if keyword:
        kw = keyword.lower()
        results = [r for r in results if any(kw in str(v).lower() for v in r.values())]
    return results


# ── 啟動時從 Google Sheets 自動同步 ──────────────────
@app.on_event("startup")
async def startup_sync():
    """啟動時自動從 Google Sheets 同步數據"""
    if SHEETS_URL:
        print(f"🔄 啟動同步 Google Sheets...")
        n = await refresh_from_sheets()
        print(f"✅ 啟動同步完成: {n} 條記錄")
    elif DATA_FILE.exists():
        # 從硬碟恢復（無 Sheets URL 時）
        global _cache_data, _cache_time
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            _cache_data = json.load(f)
        _cache_time = __import__("time").time()
        print(f"✅ 從本機恢復 {len(_cache_data)} 條記錄")
    else:
        print("⚠️ 無數據來源")


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

    # 檢查黑名單
    if user_data["id"] in BLOCKED_USERS:
        return HTMLResponse("<h1>⚠️ 您的帳號已被禁止訪問</h1>", status_code=403)

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


@app.get("/data")
async def get_data(request: Request):
    """获取全部数据（用于下拉框选项，需登录）"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)
    data = await get_cached_data()
    return JSONResponse({
        "total": len(data),
        "columns": list(data[0].keys()) if data else [],
        "results": data,
    })


@app.get("/status")
async def status_endpoint(request: Request):
    """診斷端點：檢查數據加載狀態"""
    user = get_current_user(request)
    if not user or not is_admin(user):
        return JSONResponse({"error": "無權限"}, status_code=403)

    import time as t
    data = await get_cached_data()
    columns = list(set().union(*(set(row.keys()) for row in data))) if data else []
    id_col = find_column(columns, "msw", "ms", "玩家id", "player", "id", "用戶id", "用户id")
    work_col = find_column(columns, "作品", "work", "項目", "项目")
    paid_col = find_column(columns, "是否繳費", "繳費", "paid", "是否已購", "购买")

    # 抓取第一條有數據的行
    sample_row = None
    for row in data:
        if row.get(id_col or "", "").strip():
            sample_row = row
            break

    return JSONResponse({
        "version": "3.0",
        "sheets_url_configured": bool(SHEETS_URL or load_sheets_url()),
        "cache_count": len(data),
        "cache_age_seconds": round(t.time() - _cache_time, 1) if _cache_time else -1,
        "columns": columns,
        "detected_id_col": id_col,
        "detected_work_col": work_col,
        "detected_paid_col": paid_col,
        "sample_row": sample_row,
    })


@app.get("/lookup")
async def lookup(
    request: Request,
    player_id: str = Query(""),
    work: str = Query(""),
):
    """玩家查询 — 检查是否繳費，返回对应结果（需登录）"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)

    if not player_id:
        return JSONResponse({"error": "请输入玩家ID"}, status_code=400)

    data = await get_cached_data()
    if not data:
        return JSONResponse({"error": "暂无数据"}, status_code=400)

    columns = list(set().union(*(set(row.keys()) for row in data)))
    id_col = find_column(columns, "msw", "ms", "玩家id", "player", "id", "用戶id", "用户id")
    work_col = find_column(columns, "作品", "work", "項目", "项目")
    paid_col = find_column(columns, "是否繳費", "繳費", "paid", "是否已購", "购买")

    if not id_col:
        return JSONResponse({"error": "表格中未找到「玩家ID」列"}, status_code=400)

    # 精確查找（無視前綴#）
    pid = player_id.strip().lstrip("#").lower()
    matching = []
    for row in data:
        if pid == str(row.get(id_col, "")).strip().lstrip("#").lower():
            if not work_col or not work or str(row.get(work_col, "")) == work:
                matching.append(row)

    if not matching:
        # 不在列表 = 未購買
        return JSONResponse({
            "found": False,
            "paid": False,
            "message": "未購買",
            "player_id": player_id,
            "work": work,
            "report": f"創作者: Bob\n作品: {work}\n檢舉對象ID: {player_id}",
            "creator": "Bob",
            "works": [],
        })

    creator_col = find_column(columns, "創作者", "作者", "creator", "author")

    # 收集所有匹配作品的資訊
    works_info = []
    for row in matching:
        w = str(row.get(work_col, "")) if work_col else ""
        p = str(row.get(paid_col, "")).strip() if paid_col else ""
        is_p = p in ("是", "yes", "Yes", "YES", "已缴费", "已繳費", "已购", "已購", "true", "True")
        c = str(row.get(creator_col, "Bob")) if creator_col else "Bob"
        works_info.append({
            "work": w,
            "paid": is_p,
            "creator": c,
            "report": f"創作者: {c}\n作品: {w}\n檢舉對象ID: {player_id}" if not is_p else "",
        })

    all_paid = all(w["paid"] for w in works_info)
    unpaid_works = [w for w in works_info if not w["paid"]]

    if all_paid:
        work_names = "、".join(w["work"] for w in works_info)
        return JSONResponse({
            "found": True,
            "paid": True,
            "all_paid": True,
            "message": f"已購買",
            "player_id": player_id,
            "work": work_names,
            "works": works_info,
        })

    # 有未購買的作品 — 生成舉報信息
    reports = [w["report"] for w in unpaid_works]
    return JSONResponse({
        "found": True,
        "paid": False,
        "all_paid": False,
        "message": f"未購買（{len(unpaid_works)}/{len(works_info)} 件）",
        "player_id": player_id,
        "work": "、".join(w["work"] for w in unpaid_works),
        "report": "\n\n".join(reports),
        "works": works_info,
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
    set_data(records)

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
    """获取当前表格信息（仅管理员）"""
    user = get_current_user(request)
    if not user or not is_admin(user):
        return JSONResponse({"total_rows": 0, "columns": []})
    data = await get_cached_data()
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


# ── Google Sheets 同步 ────────────────────────────────
@app.get("/sheets/url")
async def get_sheets_url(request: Request):
    """获取已保存的 Google Sheets URL（仅管理员）"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)
    if not is_admin(user):
        return JSONResponse({"error": "无权限"}, status_code=403)
    return JSONResponse({"url": load_sheets_url()})


@app.post("/sheets/sync")
async def sync_sheets(request: Request):
    """从 Google Sheets 同步数据（仅管理员）"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)
    if not is_admin(user):
        return JSONResponse({"error": "无权限, 仅管理员可操作"}, status_code=403)

    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "URL 不能为空"}, status_code=400)

    # 确保是 CSV 导出链接
    if "output=csv" not in url:
        return JSONResponse({
            "error": "请使用 Google Sheets 的 CSV 发布链接。\n"
                     "获取方式：文件 → 共享 → 发布到网络 → 逗号分隔值(.csv)"
        }, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return JSONResponse({"error": f"获取数据失败, HTTP {resp.status_code}"}, status_code=400)

            content = resp.text
            if not content.strip():
                return JSONResponse({"error": "Google Sheets 返回空数据"}, status_code=400)

            df = pd.read_csv(io.StringIO(content))
            df = df.fillna("")

    except Exception as e:
        return JSONResponse({"error": f"解析失败: {str(e)}"}, status_code=400)

    records = df.to_dict(orient="records")
    set_data(records)
    save_sheets_url(url)

    return JSONResponse({
        "message": "同步成功",
        "rows": len(records),
        "columns": list(df.columns),
    })


# ── 启动 ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
