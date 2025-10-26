import os
from typing import List, Optional
from dotenv import load_dotenv
import mysql.connector
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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
app = FastAPI(title="FoodCo Finished Products API", version="1.0")

class FinishedProductItem(BaseModel):
    product_id: int
    product_name: str
    quantity: float
    low_stock: float
    # time_update excluded

class CreateFinishedProductRequest(BaseModel):
    product_name: str = Field(..., max_length=100)
    quantity: float = Field(0, ge=0)
    low_stock: float = Field(0, ge=0)

#------------------API Endpoints------------------
@app.get("/api/finished_products", response_model=List[FinishedProductItem])
def list_finished_products():
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    results: list[FinishedProductItem] = []
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "finished_products"):
            raise HTTPException(status_code=500, detail="Table 'finished_products' not found.")
        sql = """
            SELECT ProductId AS product_id, ProductName AS product_name, Quantity AS quantity, LowStock AS low_stock
            FROM finished_products
            ORDER BY ProductId ASC
        """
        cur.execute(sql)
        for row in cur.fetchall():
            results.append(FinishedProductItem(**row))
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

@app.post("/api/finished_products", response_model=FinishedProductItem)
def create_finished_product(payload: CreateFinishedProductRequest):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "finished_products"):
            raise HTTPException(status_code=500, detail="Table 'finished_products' not found.")
        # Check for unique name
        cur.execute("SELECT 1 FROM finished_products WHERE ProductName=%s LIMIT 1", (payload.product_name,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="ProductName already exists.")
        sql = """
            INSERT INTO finished_products (ProductName, Quantity, LowStock)
            VALUES (%s, %s, %s)
        """
        cur.execute(sql, (payload.product_name, payload.quantity, payload.low_stock))
        cnx.commit()
        new_id = cur.lastrowid
        cur.execute("SELECT ProductId AS product_id, ProductName AS product_name, Quantity AS quantity, LowStock AS low_stock FROM finished_products WHERE ProductId=%s", (new_id,))
        row = cur.fetchone()
        return FinishedProductItem(**row)
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

@app.get("/api/finished_products/{product_id}", response_model=FinishedProductItem)
def get_finished_product(product_id: int):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "finished_products"):
            raise HTTPException(status_code=500, detail="Table 'finished_products' not found.")
        sql = """
            SELECT ProductId AS product_id, ProductName AS product_name, Quantity AS quantity, LowStock AS low_stock
            FROM finished_products
            WHERE ProductId=%s
        """
        cur.execute(sql, (product_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Finished product not found.")
        return FinishedProductItem(**row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get finished product failed: {e}")
    finally:
        try:
            cur.close()
            cnx.close()
        except Exception:
            pass
