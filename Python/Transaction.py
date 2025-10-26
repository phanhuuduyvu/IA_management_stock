import os
from typing import List, Optional, Literal
from dotenv import load_dotenv
import mysql.connector
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, root_validator, model_validator

#------------------Load_env------------------
load_dotenv()
DB_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("MYSQL_PORT", "3306"))
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASS = os.getenv("MYSQL_PASSWORD", "")
DB_NAME = os.getenv("MYSQL_DB", "FoodCo_Management")

#------------------Database_Connection------------------
def get_conn():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME
    )

def table_exists(cur, table_name: str) -> bool:
    cur.execute("SHOW TABLES LIKE %s", (table_name,))
    return cur.fetchone() is not None

def get_columns(cur, table_name: str) -> set:
    cur.execute(f"DESCRIBE `{table_name}`")
    rows = cur.fetchall() or []
    if not rows:
        return set()
    if not isinstance(rows[0], dict):
        return {r[0] for r in rows}
    return {r.get("Field") for r in rows if "Field" in r}

#------------------FastAPI------------------
app = FastAPI(title="FoodCo Inventory Transactions API", version="1.0")

class InventoryTransactionItem(BaseModel):
    transaction_id: int
    transaction_type: Literal['Import', 'Export']
    item_type: Literal['RawMaterial', 'FinishedProduct']
    materials_id: Optional[int] = None
    product_id: Optional[int] = None
    qty: float
    before_qty: Optional[float] = None
    after_qty: Optional[float] = None
    note: Optional[str] = None
    changed_by: int
    # time_update excluded

class CreateInventoryTransactionRequest(BaseModel):
    transaction_type: Literal['Import', 'Export']
    item_type: Literal['RawMaterial', 'FinishedProduct']
    materials_id: Optional[int] = None
    product_id: Optional[int] = None
    qty: float = Field(..., gt=0)
    before_qty: Optional[float] = None
    after_qty: Optional[float] = None
    note: Optional[str] = None
    changed_by: int

    @model_validator(mode="after")
    def check_item_exclusive(self):
        if self.item_type == 'RawMaterial':
            if not self.materials_id or self.product_id:
                raise ValueError('For RawMaterial, materials_id must be set and product_id must be null')
        elif self.item_type == 'FinishedProduct':
            if not self.product_id or self.materials_id:
                raise ValueError('For FinishedProduct, product_id must be set and materials_id must be null')
        return self

#------------------API Endpoints------------------
@app.get("/api/inventory_transactions", response_model=List[InventoryTransactionItem])
def list_inventory_transactions():
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    results: list[InventoryTransactionItem] = []
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "inventory_transactions"):
            raise HTTPException(status_code=500, detail="Table 'inventory_transactions' not found.")
        sql = """
            SELECT TransactionID AS transaction_id, TransactionType AS transaction_type, ItemType AS item_type,
                   MaterialsId AS materials_id, ProductId AS product_id, Qty AS qty, BeforeQty AS before_qty,
                   AfterQty AS after_qty, Note AS note, ChangedBy AS changed_by
            FROM inventory_transactions
            ORDER BY TransactionID ASC
        """
        cur.execute(sql)
        for row in cur.fetchall():
            results.append(InventoryTransactionItem(**row))
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    finally:
        try:
            cur.close()
            cnx.close()
        except Exception:
            pass

@app.post("/api/inventory_transactions", response_model=InventoryTransactionItem)
def create_inventory_transaction(payload: CreateInventoryTransactionRequest):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "inventory_transactions"):
            raise HTTPException(status_code=500, detail="Table 'inventory_transactions' not found.")
        # Check foreign keys (ChangedBy, MaterialsId, ProductId)
        # Only check the relevant item FK
        if payload.item_type == 'RawMaterial':
            cur.execute("SELECT 1 FROM raw_materials WHERE MaterialsId=%s", (payload.materials_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="RawMaterial not found.")
        elif payload.item_type == 'FinishedProduct':
            cur.execute("SELECT 1 FROM finished_products WHERE ProductId=%s", (payload.product_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="FinishedProduct not found.")
        cur.execute("SELECT 1 FROM users WHERE UserID=%s", (payload.changed_by,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail="ChangedBy user not found.")
        sql = """
            INSERT INTO inventory_transactions (TransactionType, ItemType, MaterialsId, ProductId, Qty, BeforeQty, AfterQty, Note, ChangedBy)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cur.execute(sql, (
            payload.transaction_type,
            payload.item_type,
            payload.materials_id,
            payload.product_id,
            payload.qty,
            payload.before_qty,
            payload.after_qty,
            payload.note,
            payload.changed_by
        ))
        cnx.commit()
        new_id = cur.lastrowid
        cur.execute("SELECT TransactionID AS transaction_id, TransactionType AS transaction_type, ItemType AS item_type, MaterialsId AS materials_id, ProductId AS product_id, Qty AS qty, BeforeQty AS before_qty, AfterQty AS after_qty, Note AS note, ChangedBy AS changed_by FROM inventory_transactions WHERE TransactionID=%s", (new_id,))
        row = cur.fetchone()
        return InventoryTransactionItem(**row)
    except mysql.connector.IntegrityError as e:
        cnx.rollback()
        raise HTTPException(status_code=400, detail=f"Integrity error: {e.msg}")
    except Exception as e:
        cnx.rollback()
        raise HTTPException(status_code=500, detail=f"Create failed: {e}")
    finally:
        try:
            cur.close()
            cnx.close()
        except Exception:
            pass

@app.get("/api/inventory_transactions/{transaction_id}", response_model=InventoryTransactionItem)
def get_inventory_transaction(transaction_id: int):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "inventory_transactions"):
            raise HTTPException(status_code=500, detail="Table 'inventory_transactions' not found.")
        sql = """
            SELECT TransactionID AS transaction_id, TransactionType AS transaction_type, ItemType AS item_type, MaterialsId AS materials_id, ProductId AS product_id, Qty AS qty, BeforeQty AS before_qty, AfterQty AS after_qty, Note AS note, ChangedBy AS changed_by
            FROM inventory_transactions
            WHERE TransactionID=%s
        """
        cur.execute(sql, (transaction_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Inventory transaction not found.")
        return InventoryTransactionItem(**row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get inventory transaction failed: {e}")
    finally:
        try:
            cur.close()
            cnx.close()
        except Exception:
            pass
