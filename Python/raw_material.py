import os
import re
import hashlib
from datetime import date
from typing import List, Optional, Literal

from dotenv import load_dotenv
import mysql.connector
from mysql.connector import errors as mysql_errors
from fastapi import FastAPI, HTTPException 
from pydantic import BaseModel, Field, validator


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
app = FastAPI(title="FoodCo Raw Materials API", version="1.0")

class RawMaterialItem(BaseModel):
    materials_id: int
    materials_name: str
    unit: str
    quantity: float
    low_stock: float

class CreateRawMaterialRequest(BaseModel):
    materials_name: str = Field(..., max_length=100)
    unit: str = Field(..., max_length=20)
    quantity: float = Field(0, ge=0)
    low_stock: float = Field(0, ge=0)

#------------------API Endpoints------------------
@app.get("/api/raw_materials", response_model=List[RawMaterialItem])
def list_raw_materials():
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    results: list[RawMaterialItem] = []
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "raw_materials"):
            raise HTTPException(status_code=500, detail="Table 'raw_materials' not found.")
        sql = """
            SELECT MaterialsId AS materials_id, MaterialsName AS materials_name, Unit AS unit, Quantity AS quantity, LowStock AS low_stock
            FROM raw_materials
            ORDER BY MaterialsId ASC
        """
        cur.execute(sql)
        for row in cur.fetchall():
            results.append(RawMaterialItem(**row))
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

@app.post("/api/raw_materials", response_model=RawMaterialItem)
def create_raw_material(payload: CreateRawMaterialRequest):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "raw_materials"):
            raise HTTPException(status_code=500, detail="Table 'raw_materials' not found.")
        # Check for unique name
        cur.execute("SELECT 1 FROM raw_materials WHERE MaterialsName=%s LIMIT 1", (payload.materials_name,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="MaterialsName already exists.")
        sql = """
            INSERT INTO raw_materials (MaterialsName, Unit, Quantity, LowStock)
            VALUES (%s, %s, %s, %s)
        """
        cur.execute(sql, (payload.materials_name, payload.unit, payload.quantity, payload.low_stock))
        cnx.commit()
        new_id = cur.lastrowid
        cur.execute("SELECT MaterialsId AS materials_id, MaterialsName AS materials_name, Unit AS unit, Quantity AS quantity, LowStock AS low_stock FROM raw_materials WHERE MaterialsId=%s", (new_id,))
        row = cur.fetchone()
        return RawMaterialItem(**row)
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

@app.get("/api/raw_materials/{material_id}", response_model=RawMaterialItem)
def get_raw_material(material_id: int):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    try:
        cur = cnx.cursor(dictionary=True)
        if not table_exists(cur, "raw_materials"):
            raise HTTPException(status_code=500, detail="Table 'raw_materials' not found.")
        sql = """
            SELECT MaterialsId AS materials_id, MaterialsName AS materials_name, Unit AS unit, Quantity AS quantity, LowStock AS low_stock
            FROM raw_materials
            WHERE MaterialsId=%s
        """
        cur.execute(sql, (material_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Raw material not found.")
        return RawMaterialItem(**row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get raw material failed: {e}")
    finally:
        try:
            cur.close()
            cnx.close()
        except Exception:
            pass