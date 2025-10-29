# main.py — Aggregate FastAPI for inventory.py, Transaction.py, user.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---- Import sub-apps (giữ nguyên cấu trúc file gốc) ----
from inventory import app as inventory_app    # /api/raw-materials, /api/finished-goods, /api/inventory, /api/health
from transaction import app as transaction_app  # /api/inventory_transactions
from user import app as user_app              # /api/users, /api/auth/*, /api/me

# ---- App chính ----
app = FastAPI(title="FoodCo Unified API", version="1.0")

# Hợp nhất CORS (chọn tập superset cho tiện dev)
origins = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:5500", "http://127.0.0.1:5500",
    "http://localhost:5501", "http://127.0.0.1:5501",
    "http://localhost:5502", "http://127.0.0.1:5502",
    "http://localhost:5503", "http://127.0.0.1:5503",
    "http://localhost:5504", "http://127.0.0.1:5504",
    "http://localhost:5505", "http://127.0.0.1:5505",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Gộp routes từ các sub-app vào app chính ----
# Lưu ý: các path đều đã bắt đầu bằng /api/... trong từng file, không trùng nhau nên merge an toàn.
app.router.routes.extend(inventory_app.router.routes)
app.router.routes.extend(transaction_app.router.routes)
app.router.routes.extend(user_app.router.routes)

# (Tuỳ chọn) Gộp exception handlers (nếu các app con có custom handler)
for exc, handler in inventory_app.exception_handlers.items():
    app.add_exception_handler(exc, handler)
for exc, handler in transaction_app.exception_handlers.items():
    app.add_exception_handler(exc, handler)
for exc, handler in user_app.exception_handlers.items():
    app.add_exception_handler(exc, handler)

# ---- Health gốc (ngoài /api/health của inventory) ----
@app.get("/")
def root():
    return {
        "ok": True,
        "service": "FoodCo Unified API",
        "docs": "/docs",
        "apis": [
            "/api/raw-materials", "/api/finished-goods", "/api/inventory",  # inventory.py
            "/api/inventory_transactions",                                   # Transaction.py
            "/api/users", "/api/auth/login", "/api/auth/refresh", "/api/me"  # user.py
        ],
    }

# ---- Dev runner ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
