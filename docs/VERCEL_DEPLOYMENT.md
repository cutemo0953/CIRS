# CIRS Vercel 部署指南

## 概述

CIRS (Community Inventory Resilience System) 可部署至 Vercel 作為線上展示版本。展示版使用記憶體資料庫 (`:memory:`)，資料在伺服器重啟後會重置。

## 部署網址

- **Demo**: https://cirs-demo.vercel.app
- **GitHub**: https://github.com/cutemo0953/CIRS (branch: `main`)

## 檔案結構

```
CIRS/
├── api/
│   └── index.py          # Vercel serverless 入口
├── backend/
│   ├── main.py           # FastAPI 主程式
│   ├── database.py       # 資料庫連接 (含 Vercel 支援)
│   ├── schema.sql        # 資料庫結構
│   ├── seeder.py         # 展示資料植入
│   └── routes/           # API 路由
├── frontend/             # 管理員 PWA
├── portal/               # 公開入口頁
└── vercel.json           # Vercel 配置
```

## 關鍵修改

### 1. 環境偵測 (`backend/database.py`)

```python
IS_VERCEL = os.environ.get("VERCEL") == "1"
DB_NAME = "xirs_hub.db"  # v2.0+, auto-migrates from cirs.db

if IS_VERCEL:
    DB_PATH = ":memory:"
else:
    DB_PATH = str(BACKEND_DIR / "data" / DB_NAME)
```

### 2. Serverless 入口 (`api/index.py`)

```python
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from backend.main import app
```

### 3. 記憶體資料庫單例模式 (`backend/database.py`)

```python
_memory_connection = None

def get_connection():
    global _memory_connection

    if IS_VERCEL:
        if _memory_connection is None:
            _memory_connection = sqlite3.connect(
                DB_PATH, check_same_thread=False, timeout=30.0
            )
            _memory_connection.row_factory = sqlite3.Row
        return _memory_connection
    else:
        # File-based mode
        return sqlite3.connect(DB_PATH, ...)
```

### 4. Context Manager 不關閉記憶體連接 (`backend/database.py`)

```python
@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # Only close for file-based mode
        if not IS_VERCEL:
            conn.close()
```

### 5. Vercel 路由配置 (`vercel.json`)

```json
{
  "version": 2,
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python",
      "config": { "maxLambdaSize": "50mb" }
    },
    { "src": "frontend/**", "use": "@vercel/static" },
    { "src": "portal/**", "use": "@vercel/static" }
  ],
  "routes": [
    { "src": "/api/(.*)", "dest": "/api/index.py" },
    { "src": "/portal/(.*)", "dest": "/portal/$1" },
    { "src": "/portal", "dest": "/portal/index.html" },
    { "src": "/frontend/(.*)", "dest": "/frontend/$1" },
    { "src": "/frontend", "dest": "/frontend/index.html" },
    { "src": "/(.*)", "dest": "/portal/$1" }
  ]
}
```

## 與 MIRS 的關鍵差異

CIRS 在設計初期即考慮 Vercel 支援，因此遇到的問題較少：

| 項目 | CIRS | MIRS |
|------|------|------|
| 資料庫管理 | Context manager (`get_db()`) | 直接連接管理 |
| 連接關閉 | 在 finally 中判斷 `IS_VERCEL` | 需要 NonClosingConnection 包裝器 |
| 路徑處理 | 使用 `pathlib` | 需改用 `PROJECT_ROOT` |
| 靜態檔案 | 前後端分離 (`frontend/`, `portal/`) | 單一 `Index.html` |
| Seeder | 獨立 `seeder.py` | 需修正欄位對應 |

## 展示模式功能

### Demo Status API
```
GET /api/demo-status
Response: {
  "is_demo": true,
  "version": "1.0.0-demo",
  "message": "此為線上展示版，資料將在頁面重整後重置",
  "github_url": "https://github.com/cutemo0953/CIRS"
}
```

### Demo Reset API
```
POST /api/demo/reset
Response: {"success": true, "message": "Demo data has been reset successfully"}
```

### Public Status API (Portal 交通燈系統)
```
GET /api/public/status
Response: {
  "shelter": {"status": "green", "headcount": 10, "capacity": 100},
  "water": {"status": "green", "days": 5.2},
  "food": {"status": "yellow", "days": 2.1},
  "equipment": {"status": "green", "issues": 0},
  "broadcast": "歡迎來到社區庇護站",
  "is_demo": true
}
```

## 部署指令

```bash
# 登入 Vercel
npx vercel login

# 部署
cd ~/Downloads/CIRS
npx vercel --prod --yes
```

## 注意事項

1. **資料暫存性**: 記憶體資料庫會在 Lambda 冷啟動時重置
2. **靜態檔案掛載**: Vercel 模式下不掛載 StaticFiles (由 vercel.json 處理)
3. **Python 路徑**: `api/index.py` 需正確設置 `sys.path`
4. **CORS**: 開發/展示模式允許所有來源

## 相關文件

- [vercel.json](../vercel.json) - Vercel 配置
- [api/index.py](../api/index.py) - Serverless 入口
- [backend/database.py](../backend/database.py) - 資料庫管理
- [backend/seeder.py](../backend/seeder.py) - 展示資料
