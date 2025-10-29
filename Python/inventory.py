# inventory.py — FastAPI CRUD + Auto-resolve table/column names (Raw/Finished)
# Supports tables: RawMaterials | raw_materials  and  FinishedGoods | finished_products
# Run: uvicorn inventory:app --reload --port 8001

import os
from datetime import datetime, timezone
from typing import List, Optional, Literal, Any, Dict, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import mysql.connector
from mysql.connector import errors as mysql_errors

# ================= ENV / DB =================
load_dotenv()
DB_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("MYSQL_PORT", "3306"))
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASS = os.getenv("MYSQL_PASSWORD", "")
DB_NAME = os.getenv("MYSQL_DB", "FoodCo_Management")

def get_conn():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME
        )
        conn.autocommit = True
        return conn
    except mysql_errors.Error as e:
        raise HTTPException(status_code=500, detail=f"DB connection error: {e.msg}")

# ================= APP =================
app = FastAPI(title="Inventory API", version="1.1 (auto-resolve table/cols)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500", "http://localhost", "http://127.0.0.1"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= MODELS =================
class RawMatCreate(BaseModel):
    MaterialName: str = Field(..., max_length=100)
    MaterialQuantity: int = Field(0, ge=0)
    Lowstock: Optional[int] = Field(None, ge=0)
    Unit: str = Field(..., max_length=10)

class RawMatUpdate(BaseModel):
    MaterialName: Optional[str] = Field(None, max_length=100)
    MaterialQuantity: Optional[int] = Field(None, ge=0)
    Lowstock: Optional[int] = Field(None, ge=0)
    Unit: Optional[str] = Field(None, max_length=10)

class FinishedCreate(BaseModel):
    FinishedGoodsName: str = Field(..., max_length=100)
    FinishedGoodsQuantity: int = Field(0, ge=0)
    Lowstock: Optional[int] = Field(None, ge=0)

class FinishedUpdate(BaseModel):
    FinishedGoodsName: Optional[str] = Field(None, max_length=100)
    FinishedGoodsQuantity: Optional[int] = Field(None, ge=0)
    Lowstock: Optional[int] = Field(None, ge=0)

class InventoryItem(BaseModel):
    id: int
    code: str
    name: str
    quantity: int
    unit: str
    lowStock: int
    updatedAt: Optional[str]
    type: Literal["Raw", "Finished"]
    status: Literal["OK", "Low", "Out"]

# ================= TABLE/COLUMN RESOLUTION =================
def resolve_table_name(cur, candidates: List[str]) -> str:
    """
    Return the first existing table name in DB among candidates (case-insensitive).
    """
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema=%s
        """,
        (DB_NAME,),
    )
    existing = {r[0].lower(): r[0] for r in cur.fetchall()}
    for cand in candidates:
        if cand.lower() in existing:
            return existing[cand.lower()]
    return ""

def resolve_column_names(cur, table: str, wanted: Dict[str, List[str]]) -> Dict[str, str]:
    """
    For given table, map logical keys -> actual column names.
    wanted = { logical: [candidate1, candidate2, ...] }
    """
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s
        """,
        (DB_NAME, table),
    )
    cols = {r[0].lower(): r[0] for r in cur.fetchall()}
    out = {}
    for key, cands in wanted.items():
        found = None
        for c in cands:
            if c.lower() in cols:
                found = cols[c.lower()]
                break
        if not found:
            raise HTTPException(status_code=500, detail=f"Column for '{key}' not found in table '{table}'")
        out[key] = found
    return out

def compute_status(qty: int, low: Optional[int]) -> str:
    if qty <= 0:
        return "Out"
    if low is not None and qty <= low:
        return "Low"
    return "OK"

# ================= HEALTH =================
@app.get("/api/health")
def health():
    return {"ok": True, "db": DB_NAME, "time": datetime.now(timezone.utc).isoformat()}

# ================= RAW MATERIALS CRUD =================
def get_raw_table_and_cols() -> Tuple[str, Dict[str,str]]:
    conn = get_conn()
    cur = conn.cursor()
    table = resolve_table_name(cur, ["RawMaterials", "raw_materials"])
    cur.close(); conn.close()
    if not table:
        raise HTTPException(status_code=500, detail="Table RawMaterials/raw_materials not found in DB")

    conn = get_conn()
    cur = conn.cursor()
    cols = resolve_column_names(cur, table, {
        # aterialsId/MaterialsName/Quantity/LowStock
        "id":       ["MaterialID", "material_id", "id",
                     "MaterialsId", "materials_id", "materialsId"],
        "name":     ["MaterialName", "material_name", "name",
                     "MaterialsName", "materials_name", "materialsName"],
        "quantity": ["MaterialQuantity", "material_quantity",
                     "Quantity", "quantity"],
        "low":      ["Lowstock", "lowstock", "low_stock", "low",
                     "LowStock"],     # viết hoa S
        "unit":     ["Unit", "unit"],
        "time":     ["TimeUpdate", "time_update", "updated_at", "update_time", "timestamp"],
    })
    cur.close(); conn.close()
    return table, cols


@app.get("/api/raw-materials")
def list_raw_materials():
    table, c = get_raw_table_and_cols()
    q = f"""SELECT `{c['id']}` AS MaterialID, `{c['name']}` AS MaterialName,
                   `{c['quantity']}` AS MaterialQuantity, `{c['low']}` AS Lowstock,
                   `{c['unit']}` AS Unit, `{c['time']}` AS TimeUpdate
            FROM `{table}` ORDER BY `{c['id']}` DESC"""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(q)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {"data": rows}

@app.get("/api/raw-materials/{material_id}")
def get_raw_material(material_id: int):
    table, c = get_raw_table_and_cols()
    q = f"""SELECT `{c['id']}` AS MaterialID, `{c['name']}` AS MaterialName,
                   `{c['quantity']}` AS MaterialQuantity, `{c['low']}` AS Lowstock,
                   `{c['unit']}` AS Unit, `{c['time']}` AS TimeUpdate
            FROM `{table}` WHERE `{c['id']}`=%s"""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(q, (material_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Raw material not found")
    return {"data": row}

@app.post("/api/raw-materials", status_code=status.HTTP_201_CREATED)
def create_raw_material(payload: RawMatCreate):
    table, c = get_raw_table_and_cols()
    q = f"""INSERT INTO `{table}`(`{c['name']}`,`{c['quantity']}`,`{c['low']}`,`{c['unit']}`)
            VALUES (%s,%s,%s,%s)"""
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(q, (payload.MaterialName, payload.MaterialQuantity, payload.Lowstock, payload.Unit))
        new_id = cur.lastrowid
    except mysql_errors.Error as e:
        raise HTTPException(status_code=400, detail=e.msg)
    finally:
        cur.close(); conn.close()
    return {"id": new_id}

@app.put("/api/raw-materials/{material_id}")
def update_raw_material(material_id: int, payload: RawMatUpdate):
    table, c = get_raw_table_and_cols()
    fields, vals = [], []
    if payload.MaterialName is not None: fields += [f"`{c['name']}`=%s"]; vals += [payload.MaterialName]
    if payload.MaterialQuantity is not None: fields += [f"`{c['quantity']}`=%s"]; vals += [payload.MaterialQuantity]
    if payload.Lowstock is not None: fields += [f"`{c['low']}`=%s"]; vals += [payload.Lowstock]
    if payload.Unit is not None: fields += [f"`{c['unit']}`=%s"]; vals += [payload.Unit]
    if not fields: raise HTTPException(status_code=400, detail="No fields to update")

    q = f"UPDATE `{table}` SET {', '.join(fields)} WHERE `{c['id']}`=%s"
    vals.append(material_id)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q, tuple(vals))
    affected = cur.rowcount
    cur.close(); conn.close()
    if affected == 0: raise HTTPException(status_code=404, detail="Raw material not found")
    return {"updated": True}

@app.delete("/api/raw-materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_raw_material(material_id: int):
    table, c = get_raw_table_and_cols()
    q = f"DELETE FROM `{table}` WHERE `{c['id']}`=%s"
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q, (material_id,))
    affected = cur.rowcount
    cur.close(); conn.close()
    if affected == 0: raise HTTPException(status_code=404, detail="Raw material not found")
    return

# ================= FINISHED GOODS CRUD =================
def get_finished_table_and_cols() -> Tuple[str, Dict[str,str]]:
    conn = get_conn(); cur = conn.cursor()
    table = resolve_table_name(cur, ["FinishedGoods", "finished_products"])
    cur.close(); conn.close()
    if not table:
        raise HTTPException(status_code=500, detail="Table FinishedGoods/finished_products not found in DB")

    conn = get_conn(); cur = conn.cursor()
    cols = resolve_column_names(cur, table, {
        # ProductId/ProductName/Quantity/LowStock
        "id":       ["GoodsID", "goods_id", "id",
                     "ProductId", "product_id", "productId"],
        "name":     ["FinishedGoodsName", "finished_goods_name", "name",
                     "ProductName", "product_name", "productName"],
        "quantity": ["FinishedGoodsQuantity", "finished_goods_quantity",
                     "Quantity", "quantity"],
        "low":      ["Lowstock", "lowstock", "low_stock", "low",
                     "LowStock"],
        "time":     ["TimeUpdate", "time_update", "updated_at", "update_time", "timestamp"],
    })
    cur.close(); conn.close()
    return table, cols


@app.get("/api/finished-goods")
def list_finished_goods():
    table, c = get_finished_table_and_cols()
    q = f"""SELECT `{c['id']}` AS GoodsID, `{c['name']}` AS FinishedGoodsName,
                   `{c['quantity']}` AS FinishedGoodsQuantity, `{c['low']}` AS Lowstock,
                   `{c['time']}` AS TimeUpdate
            FROM `{table}` ORDER BY `{c['id']}` DESC"""
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    cur.execute(q); rows = cur.fetchall()
    cur.close(); conn.close()
    return {"data": rows}

@app.get("/api/finished-goods/{goods_id}")
def get_finished_goods(goods_id: int):
    table, c = get_finished_table_and_cols()
    q = f"""SELECT `{c['id']}` AS GoodsID, `{c['name']}` AS FinishedGoodsName,
                   `{c['quantity']}` AS FinishedGoodsQuantity, `{c['low']}` AS Lowstock,
                   `{c['time']}` AS TimeUpdate
            FROM `{table}` WHERE `{c['id']}`=%s"""
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    cur.execute(q, (goods_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row: raise HTTPException(status_code=404, detail="Finished goods not found")
    return {"data": row}

@app.post("/api/finished-goods", status_code=status.HTTP_201_CREATED)
def create_finished_goods(payload: FinishedCreate):
    table, c = get_finished_table_and_cols()
    q = f"""INSERT INTO `{table}`(`{c['name']}`,`{c['quantity']}`,`{c['low']}`)
            VALUES (%s,%s,%s)"""
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(q, (payload.FinishedGoodsName, payload.FinishedGoodsQuantity, payload.Lowstock))
        new_id = cur.lastrowid
    except mysql_errors.Error as e:
        raise HTTPException(status_code=400, detail=e.msg)
    finally:
        cur.close(); conn.close()
    return {"id": new_id}

@app.put("/api/finished-goods/{goods_id}")
def update_finished_goods(goods_id: int, payload: FinishedUpdate):
    table, c = get_finished_table_and_cols()
    fields, vals = [], []
    if payload.FinishedGoodsName is not None: fields += [f"`{c['name']}`=%s"]; vals += [payload.FinishedGoodsName]
    if payload.FinishedGoodsQuantity is not None: fields += [f"`{c['quantity']}`=%s"]; vals += [payload.FinishedGoodsQuantity]
    if payload.Lowstock is not None: fields += [f"`{c['low']}`=%s"]; vals += [payload.Lowstock]
    if not fields: raise HTTPException(status_code=400, detail="No fields to update")
    q = f"UPDATE `{table}` SET {', '.join(fields)} WHERE `{c['id']}`=%s"
    vals.append(goods_id)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q, tuple(vals))
    affected = cur.rowcount
    cur.close(); conn.close()
    if affected == 0: raise HTTPException(status_code=404, detail="Finished goods not found")
    return {"updated": True}

@app.delete("/api/finished-goods/{goods_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_finished_goods(goods_id: int):
    table, c = get_finished_table_and_cols()
    q = f"DELETE FROM `{table}` WHERE `{c['id']}`=%s"
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q, (goods_id,))
    affected = cur.rowcount
    cur.close(); conn.close()
    if affected == 0: raise HTTPException(status_code=404, detail="Finished goods not found")
    return

# ================= JOIN VIEW (UI) =================
def normalize_row_to_item(row: Dict[str, Any], kind: Literal["Raw","Finished"]) -> InventoryItem:
    qty = int(row["quantity"] or 0)
    low = row.get("lowStock")
    status = compute_status(qty, low)
    upd = row.get("updatedAt")
    return InventoryItem(
        id=int(row["id"]),
        code=("RM-" if kind=="Raw" else "FG-") + f"{int(row['id']):04d}",
        name=row["name"],
        quantity=qty,
        unit=(row.get("unit") or "-") if kind=="Raw" else "-",
        lowStock=int(low or 0),
        updatedAt=upd.isoformat() if isinstance(upd, datetime) else str(upd) if upd else None,
        type=kind,
        status=status
    )

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    type: Optional[Literal["Raw","Finished"]] = Query(None),
    status_f: Optional[Literal["OK","Low","Out"]] = Query(None, alias="status"),
    in_stock_only: Optional[bool] = Query(False, alias="inStockOnly"),
    search: Optional[str] = Query(None)
):
    # RAW: build SELECT with aliases to a unified shape
    r_table, rc = get_raw_table_and_cols()
    r_select = f"""
      SELECT `{rc['id']}` AS id,
             `{rc['name']}` AS name,
             `{rc['quantity']}` AS quantity,
             `{rc['unit']}` AS unit,
             `{rc['low']}` AS lowStock,
             `{rc['time']}` AS updatedAt
      FROM `{r_table}`
    """

    f_table, fc = get_finished_table_and_cols()
    f_select = f"""
      SELECT `{fc['id']}` AS id,
             `{fc['name']}` AS name,
             `{fc['quantity']}` AS quantity,
             '-' AS unit,
             `{fc['low']}` AS lowStock,
             `{fc['time']}` AS updatedAt
      FROM `{f_table}`
    """

    conn = get_conn(); cur = conn.cursor(dictionary=True)
    cur.execute(r_select); raw_rows = cur.fetchall()
    cur.execute(f_select); fin_rows = cur.fetchall()
    cur.close(); conn.close()

    items: List[InventoryItem] = [normalize_row_to_item(r, "Raw") for r in raw_rows] + \
                                 [normalize_row_to_item(g, "Finished") for g in fin_rows]

    # Optional server-side filters (match frontend)
    s = (search or "").strip().lower()
    out: List[InventoryItem] = []
    for it in items:
        if type and it.type != type: continue
        if status_f and it.status != status_f: continue
        if in_stock_only and it.quantity <= 0: continue
        if s and (s not in it.name.lower() and s not in it.code.lower()): continue
        out.append(it)

    out.sort(key=lambda x: (x.type, x.id), reverse=True)
    return out
