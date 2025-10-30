# transaction.py — FastAPI CRUD for inventory transactions (Pydantic v2)
# Run: uvicorn transaction:app --reload --port 8001

import os
from datetime import datetime, timezone, date
from typing import Optional, List, Literal, Dict, Any, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator
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
app = FastAPI(title="Transactions API", version="1.1 (enum-aware)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500","http://127.0.0.1:5500",
        "http://localhost:5501","http://127.0.0.1:5501",
        "http://localhost:5502","http://127.0.0.1:5502",
        "http://localhost:5503","http://127.0.0.1:5503",
        "http://localhost","http://127.0.0.1",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= HELPERS (schema resolution) =================
def resolve_table_name(cur, candidates: List[str]) -> str:
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
        (DB_NAME,),
    )
    existing = {r[0].lower(): r[0] for r in cur.fetchall()}
    for cand in candidates:
        if cand.lower() in existing:
            return existing[cand.lower()]
    return ""

def resolve_column_names(cur, table: str, wanted: Dict[str, List[str]]) -> Dict[str, str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
        (DB_NAME, table),
    )
    cols = {r[0].lower(): r[0] for r in cur.fetchall()}
    out: Dict[str, str] = {}
    missing = []
    for key, cands in wanted.items():
        found = None
        for c in cands:
            if c.lower() in cols:
                found = cols[c.lower()]
                break
        if not found:
            missing.append(key)
        else:
            out[key] = found
    if missing:
        raise HTTPException(status_code=500, detail=f"Column(s) {missing} not found in table '{table}'")
    return out

def get_tx_table_and_cols() -> Tuple[str, Dict[str, str]]:
    conn = get_conn(); cur = conn.cursor()
    table = resolve_table_name(cur, ["inventory_transactions", "InventoryTransactions", "transactions", "Transactions"])
    cur.close(); conn.close()
    if not table:
        raise HTTPException(status_code=500, detail="Table inventory_transactions not found")

    conn = get_conn(); cur = conn.cursor()
    cols = resolve_column_names(cur, table, {
        "id":          ["TransactionID", "transaction_id", "id"],
        "txType":      ["TransactionType", "transaction_type", "Type"],
        "itemType":    ["ItemType", "item_type"],
        "materialsId": ["MaterialsId", "MaterialID", "material_id", "materials_id"],
        "productId":   ["ProductId", "product_id", "GoodsID", "goods_id"],
        "qty":         ["Qty", "Quantity", "quantity", "qty"],
        "beforeQty":   ["BeforeQty", "before_qty"],
        "afterQty":    ["AfterQty", "after_qty"],
        "note":        ["Note", "note", "Description", "description"],
        "changedBy":   ["ChangedBy", "UserID", "changed_by"],
        "time":        ["TimeUpdate", "time_update", "updated_at", "timestamp", "CreatedAt", "created_at"],
    })
    cur.close(); conn.close()
    return table, cols

# ---------- ENUM helpers (read actual enum list & coerce value) ----------
def get_enum_values(cur, table: str, column: str) -> List[str]:
    cur.execute("""
        SELECT COLUMN_TYPE
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s AND column_name=%s
    """, (DB_NAME, table, column))
    row = cur.fetchone()
    if not row or not row[0]:
        return []
    coltype = row[0]  # e.g. "enum('RawMaterial','FinishedProduct')"
    s = coltype.strip()
    if not s.lower().startswith("enum(") or not s.endswith(")"):
        return []
    inside = s[s.find("(")+1:-1]
    vals = []
    cur_val = []
    in_quote = False
    for ch in inside:
        if ch == "'":
            in_quote = not in_quote
            continue
        if ch == "," and not in_quote:
            vals.append("".join(cur_val).strip())
            cur_val = []
        else:
            cur_val.append(ch)
    if cur_val:
        vals.append("".join(cur_val).strip())
    return [v for v in vals if v]

def coerce_item_type_for_db(requested: str, allowed: List[str]) -> str:
    """Map Raw/RawMaterial/RawMaterials and Finished/FinishedProduct/FinishedGoods
    to the actual DB enum values."""
    if not requested:
        raise HTTPException(status_code=400, detail="ItemType is required")

    r = requested.strip().lower()
    want_raw = r in {"raw", "rawmaterial", "rawmaterials"}
    want_fin = r in {"finished", "finishedproduct", "finishedgoods"}

    if not allowed:
        # not an enum column → keep as-is
        return requested

    # Exact match ignoring case
    for a in allowed:
        if a.lower() == r:
            return a

    # Prefer prefixes if groups are requested
    if want_raw:
        for a in allowed:
            if a.lower().startswith("raw"):
                return a
    if want_fin:
        for a in allowed:
            if a.lower().startswith("finished"):
                return a

    # Fallback: first allowed (but better to error to avoid silent mismatch)
    raise HTTPException(status_code=400, detail=f"ItemType '{requested}' is not allowed; allowed={allowed}")

def is_raw_item(mapped_item_type: str) -> bool:
    return mapped_item_type.strip().lower().startswith("raw")

# ================= MODELS =================
ItemTypeIn = Literal["Raw", "RawMaterial", "RawMaterials", "Finished", "FinishedProduct", "FinishedGoods"]
TxTypeIn   = Literal["Import", "Export"]

def _normalize_item_type(v: str) -> str:
    v_low = v.strip().lower()
    if v_low in ("raw", "rawmaterial", "rawmaterials"): return "RawMaterials"
    if v_low in ("finished", "finishedproduct", "finishedgoods"): return "FinishedGoods"
    return v

class TxCreate(BaseModel):
    TransactionType: TxTypeIn
    ItemType: ItemTypeIn
    MaterialsId: Optional[int] = None
    ProductId: Optional[int] = None
    Qty: float = Field(..., gt=0)
    Note: Optional[str] = Field(None, max_length=255)
    ChangedBy: int

    @field_validator("ItemType", mode="before")
    @classmethod
    def _norm_item_type(cls, v):
        return _normalize_item_type(v)

    @model_validator(mode="after")
    def _check_ids(self):
        if self.ItemType == "RawMaterials":
            if self.MaterialsId is None or self.ProductId is not None:
                raise ValueError("For ItemType=RawMaterials, provide MaterialsId and leave ProductId NULL")
        elif self.ItemType == "FinishedGoods":
            if self.ProductId is None or self.MaterialsId is not None:
                raise ValueError("For ItemType=FinishedGoods, provide ProductId and leave MaterialsId NULL")
        return self

class TxUpdate(BaseModel):
    TransactionType: Optional[TxTypeIn] = None
    ItemType: Optional[ItemTypeIn] = None
    MaterialsId: Optional[int] = None
    ProductId: Optional[int] = None
    Qty: Optional[float] = Field(None, gt=0)
    Note: Optional[str] = Field(None, max_length=255)
    ChangedBy: Optional[int] = None

    @field_validator("ItemType", mode="before")
    @classmethod
    def _norm_item_type(cls, v):
        return _normalize_item_type(v) if v is not None else v

    @model_validator(mode="after")
    def _check_combo(self):
        if self.ItemType == "RawMaterials":
            if self.ProductId not in (None, 0):
                raise ValueError("For ItemType=RawMaterials, ProductId must be NULL")
            if self.MaterialsId is None:
                raise ValueError("For ItemType=RawMaterials, MaterialsId is required")
        elif self.ItemType == "FinishedGoods":
            if self.MaterialsId not in (None, 0):
                raise ValueError("For ItemType=FinishedGoods, MaterialsId must be NULL")
            if self.ProductId is None:
                raise ValueError("For ItemType=FinishedGoods, ProductId is required")
        return self

class TxOut(BaseModel):
    TransactionID: int
    TransactionType: str
    ItemType: str
    MaterialsId: Optional[int] = None
    ProductId: Optional[int] = None
    Qty: float
    BeforeQty: Optional[float] = None
    AfterQty: Optional[float] = None
    Note: Optional[str] = None
    ChangedBy: int
    TimeUpdate: Optional[datetime] = None

# ================= HEALTH =================
@app.get("/api/tx/health")
def health():
    return {"ok": True, "db": DB_NAME, "time": datetime.now(timezone.utc).isoformat()}

# ================= CRUD =================
@app.get("/api/transactions", response_model=List[TxOut])
def list_transactions(
    tx_type: Optional[TxTypeIn] = Query(None, alias="type"),
    item_type: Optional[ItemTypeIn] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    changed_by: Optional[int] = Query(None),
):
    table, c = get_tx_table_and_cols()
    where, vals = [], []
    if tx_type:
        where.append(f"`{c['txType']}`=%s"); vals.append(tx_type)
    if item_type:
        where.append(f"`{c['itemType']}`=%s")
        # map item_type from request to DB enum value
        conn = get_conn(); cur = conn.cursor()
        try:
            allowed = get_enum_values(cur, table, c['itemType'])
            mapped = coerce_item_type_for_db(_normalize_item_type(item_type), allowed)
            vals.append(mapped)
        finally:
            cur.close(); conn.close()
    if changed_by is not None:
        where.append(f"`{c['changedBy']}`=%s"); vals.append(changed_by)
    if from_date:
        where.append(f"DATE(`{c['time']}`) >= %s"); vals.append(from_date.isoformat())
    if to_date:
        where.append(f"DATE(`{c['time']}`) <= %s"); vals.append(to_date.isoformat())

    q = f"""
      SELECT `{c['id']}`   AS TransactionID,
             `{c['txType']}` AS TransactionType,
             `{c['itemType']}` AS ItemType,
             `{c['materialsId']}` AS MaterialsId,
             `{c['productId']}`   AS ProductId,
             `{c['qty']}`         AS Qty,
             `{c['beforeQty']}`   AS BeforeQty,
             `{c['afterQty']}`    AS AfterQty,
             `{c['note']}`        AS Note,
             `{c['changedBy']}`   AS ChangedBy,
             `{c['time']}`        AS TimeUpdate
      FROM `{table}`
      {('WHERE ' + ' AND '.join(where)) if where else ''}
      ORDER BY `{c['id']}` DESC
    """
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    cur.execute(q, tuple(vals))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

@app.get("/api/transactions/{tx_id}", response_model=TxOut)
def get_transaction(tx_id: int):
    table, c = get_tx_table_and_cols()
    q = f"""
      SELECT `{c['id']}` AS TransactionID, `{c['txType']}` AS TransactionType,
             `{c['itemType']}` AS ItemType, `{c['materialsId']}` AS MaterialsId,
             `{c['productId']}` AS ProductId, `{c['qty']}` AS Qty,
             `{c['beforeQty']}` AS BeforeQty, `{c['afterQty']}` AS AfterQty,
             `{c['note']}` AS Note, `{c['changedBy']}` AS ChangedBy,
             `{c['time']}` AS TimeUpdate
      FROM `{table}` WHERE `{c['id']}`=%s
    """
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    cur.execute(q, (tx_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return row

@app.post("/api/transactions", status_code=status.HTTP_201_CREATED)
def create_transaction(payload: TxCreate):
    table, c = get_tx_table_and_cols()

    # Map ItemType from request → actual DB enum value
    conn = get_conn(); cur = conn.cursor()
    try:
        allowed = get_enum_values(cur, table, c['itemType'])
        mapped_item_type = coerce_item_type_for_db(payload.ItemType, allowed)
    finally:
        cur.close(); conn.close()

    fields = [c['txType'], c['itemType'], c['qty'], c['changedBy']]
    placeholders = ["%s", "%s", "%s", "%s"]
    values: List[Any] = [payload.TransactionType, mapped_item_type, payload.Qty, payload.ChangedBy]

    # Only one of MaterialsId/ProductId
    if is_raw_item(mapped_item_type):
        fields.append(c['materialsId']); placeholders.append("%s"); values.append(payload.MaterialsId)
    else:
        fields.append(c['productId']);   placeholders.append("%s"); values.append(payload.ProductId)

    if payload.Note is not None:
        fields.append(c['note']); placeholders.append("%s"); values.append(payload.Note)

    q = f"INSERT INTO `{table}`({', '.join('`'+f+'`' for f in fields)}) VALUES ({', '.join(placeholders)})"
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(q, tuple(values))
        new_id = cur.lastrowid
    except mysql_errors.Error as e:
        raise HTTPException(status_code=400, detail=e.msg)
    finally:
        cur.close(); conn.close()
    return {"id": new_id}

@app.put("/api/transactions/{tx_id}")
def update_transaction(tx_id: int, payload: TxUpdate):
    table, c = get_tx_table_and_cols()
    fields: List[str] = []
    vals: List[Any] = []

    if payload.TransactionType is not None:
        fields.append(f"`{c['txType']}`=%s"); vals.append(payload.TransactionType)

    mapped_item_type: Optional[str] = None
    if payload.ItemType is not None:
        # Map ItemType to DB enum value
        conn = get_conn(); cur = conn.cursor()
        try:
            allowed = get_enum_values(cur, table, c['itemType'])
            mapped_item_type = coerce_item_type_for_db(payload.ItemType, allowed)
        finally:
            cur.close(); conn.close()

        fields.append(f"`{c['itemType']}`=%s"); vals.append(mapped_item_type)
        # flip the opposite foreign key to NULL
        if is_raw_item(mapped_item_type):
            fields.append(f"`{c['productId']}`=NULL")
        else:
            fields.append(f"`{c['materialsId']}`=NULL")

    if payload.MaterialsId is not None:
        fields.append(f"`{c['materialsId']}`=%s"); vals.append(payload.MaterialsId)
    if payload.ProductId is not None:
        fields.append(f"`{c['productId']}`=%s"); vals.append(payload.ProductId)
    if payload.Qty is not None:
        fields.append(f"`{c['qty']}`=%s"); vals.append(payload.Qty)
    if payload.Note is not None:
        fields.append(f"`{c['note']}`=%s"); vals.append(payload.Note)
    if payload.ChangedBy is not None:
        fields.append(f"`{c['changedBy']}`=%s"); vals.append(payload.ChangedBy)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    q = f"UPDATE `{table}` SET {', '.join(fields)} WHERE `{c['id']}`=%s"
    vals.append(tx_id)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q, tuple(vals))
    affected = cur.rowcount
    cur.close(); conn.close()
    if affected == 0:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"updated": True}

@app.delete("/api/transactions/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(tx_id: int):
    table, c = get_tx_table_and_cols()
    q = f"DELETE FROM `{table}` WHERE `{c['id']}`=%s"
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q, (tx_id,))
    affected = cur.rowcount
    cur.close(); conn.close()
    if affected == 0:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return
