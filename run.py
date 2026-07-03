"""
启动脚本 — 读取 .env 环境变量后启动 FastAPI
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
env_file = BASE_DIR / ".env"
if env_file.exists():
    load_dotenv(env_file)

if __name__ == "__main__":
    import uvicorn
    from app import app

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))

    print(f"🚀 启动 Discord Query App: http://localhost:{port}")
    print(f"   Discord Client ID: {os.environ.get('DISCORD_CLIENT_ID', '未设置')}")
    print(f"   Redirect URI: {os.environ.get('DISCORD_REDIRECT_URI', '未设置')}")
    print(f"   Admin ID: {os.environ.get('ADMIN_DISCORD_ID', '未设置')}")
    print()

    uvicorn.run(app, host=host, port=port)
