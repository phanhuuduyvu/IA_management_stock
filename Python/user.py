import os
import re
import hashlib
from datetime import date
from typing import List, Optional, Literal

from dotenv import load_dotenv
import mysql.connector
from mysql.connector import errors as mysql_errors
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, validator


#------------------Load_env------------------
load_dotenv()
DB_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("MYSQL_PORT", "3306"))
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASS = os.getenv("MYSQL_PASSWORD", "")
DB_NAME = os.getenv("MYSQL_DB", "FoodCo_Management")

#------------------Regex-----------------
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,30}$")
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


#------------------FastAPI-----------------
app = FastAPI(title="FoodCo API", version="1.0")

class CreateUserRequest(BaseModel):
    username: str = Field(..., description="Username 3-30 a-zA-Z0-9")
    email: str
    password: str = Field(..., min_length=8)
    phone: Optional[str] = Field(None, max_length=20, description="users.PhoneNumber / user.Phonenumber")
    birthdate: Optional[date] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = Field(True, description="users.IsActive (1/0)")

    @validator("username")
    def _check_username(cls, v: str):
        v = v.strip()
        if not USERNAME_RE.match(v):
            raise ValueError("Invalid username format (must be 3-30 alphanumeric)")
        return v

    @validator("email")
    def _check_email(cls, v: str):
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("Invalid email format")
        return v
    
class CreateUserResponse(BaseModel):
    user_id: int 
    table_used: Literal["users", "user"]
    username: str
    email: str

class UserItem(BaseModel):
    user_id: int
    table_used: Literal["users", "user"]
    username: str
    email: str
    phone: Optional[str] = None
    birthdate: Optional[date] = None
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None

class CreateUserRequest(BaseModel):
    username: str = Field(..., description="Username 3-30 a-zA-Z0-9")
    email: str
    password: str = Field(..., min_length=8)
    phone: Optional[str] = Field(None, max_length=20, description="users.PhoneNumber / user.Phonenumber")
    birthdate: Optional[date] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = Field(True, description="users.IsActive (1/0)")

    @validator("username")
    def _check_username(cls, v: str):
        v = v.strip()
        if not USERNAME_RE.match(v):
            raise ValueError("Invalid username format (must be 3-30 alphanumeric)")
        return v

    @validator("email")
    def _check_email(cls, v: str):
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("Invalid email format")
        return v
    
def get_conn(): 
    return mysql.connector.connect(
        host = DB_HOST,
        port = DB_PORT,
        user = DB_USER,
        password = DB_PASS,
        database = DB_NAME
    )
def  table_exists(cur, table_name: str) -> bool: 
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


def get_column_type(cur, table_name: str, column_name: str) -> Optional[str]:
    cur.execute("SHOW COLUMNS FROM `{}` LIKE %s".format(table_name), (column_name,))
    row = cur.fetchone()
    if not row:
        return None 
    if isinstance(row, dict):
        return row.get("Type")
    return row[1] if len(row)>1 else None


def username_exists(cur, username: str) -> bool:
    if table_exists(cur, "users"):
        cur.execute("SELECT 1 FROM `users` WHERE `UserName`=%s LIMIT 1", (username,))
        if cur.fetchone():
            return True
    if table_exists(cur, "user"):
        cur.execute("SELECT 1 FROM `user` WHERE `Username`=%s LIMIT 1", (username,))
        if cur.fetchone():
            return True
    return False

def email_exists(cur, email: str) -> bool:
    if table_exists(cur, "users"):
        cur.execute("SELECT 1 FROM `users` WHERE `Email`=%s LIMIT 1", (email,))
        if cur.fetchone():
            return True
    if table_exists(cur, "user"):
        cur.execute("SELECT 1 FROM `user` WHERE `Email`=%s LIMIT 1", (email,))
        if cur.fetchone():
            return True
    return False

def get_users_pk(cur) -> str:
    cols = get_columns(cur, "users")
    if "UserID" in cols:
        return "UserID"
    if "user_id" in cols:
        return "user_id"
    if "id" in cols:
        return "id"
    cur.execute("SHOW KEYS FROM `users` WHERE `Key_name` = 'PRIMARY'")
    row =  cur.fetchone()
    if row and not isinstance(row, dict) and len(row) >= 5:
        return row[4]
    if row and isinstance(row, dict):
        return row.get("Column_name", "UserID")
    return "UserID"

def find_user_location(cur, user_id: int) -> tuple[str, str]:
    has_users = table_exists(cur, "users")
    has_user = table_exists(cur, "user")

    if has_users:
        pk = get_users_pk(cur)
        cur.execute(f"SELECT 1 FROM `users` WHERE `{pk}`=%s LIMIT 1", (user_id,))
        if cur.fetchone():
            return "users", pk

    if has_user:
        cur.execute("SELECT 1 FROM `user` WHERE `UserID`=%s LIMIT 1", (user_id,))
        if cur.fetchone():
            return "user", "UserID"

    raise HTTPException(status_code=404, detail="User not found.")


def get_user_item(cur, table_name: str, pk: str, user_id: int) -> Optional[dict]:
    if table_name == "users":
        cols = get_columns(cur, "users")
        select_fields = [
            f"u.`{pk}` AS user_id",
            "u.`UserName` AS username",
            "u.`Email` AS email",
        ]
        if "PhoneNumber" in cols:
            select_fields.append("u.`PhoneNumber` AS phone")
        if "BirthDate" in cols:
            select_fields.append("u.`BirthDate` AS birthdate")
        if "RoleID" in cols:
            select_fields.append("u.`RoleID` AS role_id")
        if "IsActive" in cols:
            select_fields.append("u.`IsActive` AS is_active")

        role_join = ""
        if "RoleID" in cols and table_exists(cur, "roles"):
            role_join = " LEFT JOIN `roles` r ON u.`RoleID` = r.`RoleID` "
            select_fields.append("r.`RoleName` AS role_name")

        sql = f"""
            SELECT {', '.join(select_fields)}
            FROM `users` u
            {role_join}
            WHERE u.`{pk}`=%s
            LIMIT 1
        """
        cur.execute(sql, (user_id,))
        return cur.fetchone()

    if table_name == "user":
        cols = get_columns(cur, "user")
        fields = [
            "u.`UserID` AS user_id",
            "u.`Username` AS username",
            "u.`Email` AS email",
        ]
        if "Phonenumber" in cols:
            fields.append("u.`Phonenumber` AS phone")
        if "Birthdate" in cols:
            fields.append("u.`Birthdate` AS birthdate")
        role_join = ""
        if "RoleID" in cols:
            fields.append("u.`RoleID` AS role_id")
            if table_exists(cur, "roles"):
                role_join = " LEFT JOIN `roles` r ON u.`RoleID` = r.`RoleID` "
                fields.append("r.`RoleName` AS role_name")

        sql = f"""
            SELECT {', '.join(fields)}
            FROM `user` u
            {role_join}
            WHERE u.`UserID`=%s
            LIMIT 1
        """
        cur.execute(sql, (user_id,))
        return cur.fetchone()

    return None
#--------------List all--------------
@app.get("/api/users", response_model=List[UserItem])
def list_user():
    try: 
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")    
    
    results: list[UserItem] = []

    try: 
        cur = cnx.cursor(dictionary=True)

        has_users = table_exists(cur, "users")
        has_user = table_exists(cur, "user")

        if not has_users and not has_user: 
            raise HTTPException(
                status_code=500,
                detail="No suitable user table found. Expected 'users' or 'user'."
            )
        
        if has_users:
            cols = get_columns(cur, "users")
            pk = get_users_pk(cur)
            select_fields = [
                f"u.`{pk}` AS user_id",
                "u.`UserName` AS username",
                "u.`Email` AS email",
            ]
            if "PhoneNumber" in cols:
                select_fields.append("u.`PhoneNumber` AS phone")
            if "BirthDate" in cols:
                select_fields.append("u.`BirthDate` AS birthdate")
            if "RoleID" in cols:
                select_fields.append("u.`RoleID` AS role_id")
            if "IsActive" in cols:
                select_fields.append("u.`IsActive` AS is_active")

            role_join = ""
            if "RoleID" in cols and table_exists(cur, "roles"):
                role_join = " LEFT JOIN `roles` r ON u.`RoleID` = r.`RoleID` "
                select_fields.append("r.`RoleName` AS role_name")

            sql_users = f"""
                SELECT {', '.join(select_fields)}
                FROM `users` u
                {role_join}
                ORDER BY u.`{pk}` ASC
            """
            cur.execute(sql_users)
            for row in cur.fetchall():
                results.append(
                    UserItem(
                        user_id=row.get("user_id"),
                        table_used="users",
                        username=row.get("username"),
                        email=row.get("email"),
                        full_name=None,
                        phone=row.get("phone"),
                        birthdate=row.get("birthdate"),
                        role_id=row.get("role_id"),
                        role_name=row.get("role_name"),
                        timezone=None,
                        is_active=bool(row["is_active"]) if row.get("is_active") is not None else None,
                    )
                )
        
        if has_user:
            cols = get_columns(cur, "user")
            select_fields = [
                f"u.`UserID` AS user_id",
                "u.`UserName` AS username",
                "u.`Email` AS email",
            ]
            if "PhoneNumber" in cols:
                select_fields.append("u.`PhoneNumber` AS phone")
            if "BirthDate" in cols:
                select_fields.append("u.`BirthDate` AS birthdate")
            if "RoleID" in cols:
                select_fields.append("u.`RoleID` AS role_id")
            if "IsActive" in cols:
                select_fields.append("u.`IsActive` AS is_active")

            role_join = ""
            if "RoleID" in cols and table_exists(cur, "roles"):
                role_join = " LEFT JOIN `roles` r ON u.`RoleID` = r.`RoleID` "
                select_fields.append("r.`RoleName` AS role_name")

            sql_users = f"""
                SELECT {', '.join(select_fields)}
                FROM `user` u
                {role_join}
                ORDER BY u.`UserID` ASC
            """
            cur.execute(sql_users)
            for row in cur.fetchall():
                results.append(
                    UserItem(
                        user_id=row.get("user_id"),
                        table_used="user",
                        username=row.get("username"),
                        email=row.get("email"),
                        full_name=None,
                        phone=row.get("phone"),
                        birthdate=row.get("birthdate"),
                        role_id=row.get("role_id"),
                        role_name=row.get("role_name"),
                        timezone=None,
                        is_active=None
                    )
                )
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


# --------------Create--------------
@app.post("/api/users", response_model=UserItem)
def create_user(payload: CreateUserRequest):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")

    try:
        cur = cnx.cursor(dictionary=True)

        has_users = table_exists(cur, "users")
        has_user = table_exists(cur, "user")
        if not has_users and not has_user:
            raise HTTPException(status_code=500, detail="No suitable user table found. Expected 'users' or 'user'.")
        table_name = "users" if has_users else "user"

        cur.execute(f"SELECT 1 FROM {table_name} WHERE UserName=%s OR email=%s LIMIT 1",
                    (payload.username, payload.email))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Username or email already exists.")

        import hashlib
        pwd_hash = hashlib.sha256(payload.password.encode("utf-8")).hexdigest()
        is_active = 1 if (payload.is_active is None or payload.is_active) else 0
        cur.execute(
                """
                INSERT INTO `users` (`UserName`, `PhoneNumber`, `Email`, `PasswordHash`, `BirthDate`, `RoleID`, `IsActive`)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload.username,   # UserName
                    payload.phone,              # PhoneNumber
                    payload.email,      # Email
                    pwd_hash,      # PasswordHash
                    payload.birthdate,          # BirthDate
                    payload.role_id,            # RoleID
                    is_active,          # IsActive
                ),
            )
        cnx.commit()
        new_id = cur.lastrowid

        return CreateUserResponse(
                user_id=new_id, table_used="users", username=payload.username, email=payload.email
            )

    except mysql.connector.IntegrityError as e:
        cnx.rollback()
        raise HTTPException(status_code=400, detail=f"Integrity error: {e.msg}")
    except Exception as e:
        cnx.rollback()
        raise HTTPException(status_code=500, detail=f"Create failed: {e}")
    finally:
        cur.close()
        cnx.close()

@app.get("/api/users/{user_id}", response_model=UserItem)
def get_user_by_id(user_id: int):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")

    try:
        cur = cnx.cursor(dictionary=True)
        table_name, pk = find_user_location(cur, user_id)
        if not table_name:
            raise HTTPException(status_code=404, detail="User not found.")
        row = get_user_item(cur, table_name, pk if table_name == "users" else "UserID", user_id)
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        
        if table_name == "users":
            return UserItem(
                user_id=row.get("user_id"),
                table_used="users",
                username=row.get("username"),
                email=row.get("email"),
                full_name=None,
                phone=row.get("phone"),
                birthdate=row.get("birthdate"),
                role_id=row.get("role_id"),
                role_name=row.get("role_name"),
                timezone=None,
                is_active=bool(row["is_active"]) if row.get("is_active") is not None else None,
            )  
        else :
            return UserItem(
                user_id=row.get("user_id"),
                table_used="user",
                username=row.get("username"),
                email=row.get("email"),
                full_name=None,
                phone=row.get("phone"),
                birthdate=row.get("birthdate"),
                role_id=row.get("role_id"),
                role_name=row.get("role_name"),
                timezone=None,
                is_active=None
            )
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

@app.put("/api/users/{user_id}", response_model=UserItem)
def update_user(user_id: int, payload: CreateUserRequest):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")

    try:
        cur = cnx.cursor(dictionary=True)
        table_name, pk = find_user_location(cur, user_id)
        if not table_name:
            raise HTTPException(status_code=404, detail="User not found.")

        cur.execute(f"SELECT 1 FROM {table_name} WHERE (UserName=%s OR Email=%s) AND {pk}<>%s LIMIT 1",
                    (payload.username, payload.email, user_id))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Username or email already exists.")

        import hashlib
        pwd_hash = hashlib.sha256(payload.password.encode("utf-8")).hexdigest()
        is_active = 1 if (payload.is_active is None or payload.is_active) else 0

        cur.execute(
                f"""
                UPDATE {table_name}
                SET UserName=%s, PhoneNumber=%s, Email=%s, PasswordHash=%s, BirthDate=%s, RoleID=%s, IsActive=%s
                WHERE {pk}=%s
                """,
                (
                    payload.username,
                    payload.phone,
                    payload.email,
                    pwd_hash,
                    payload.birthdate,
                    payload.role_id,
                    is_active,
                    user_id,
                ),
            )
        cnx.commit()

        row = get_user_item(cur, table_name, pk if table_name == "users" else "UserID", user_id)
        if not row:
            raise HTTPException(status_code=404, detail="User not found after update.")

        if table_name == "users":
            return UserItem(
                user_id=row.get("user_id"),
                table_used="users",
                username=row.get("username"),
                email=row.get("email"),
                full_name=None,
                phone=row.get("phone"),
                birthdate=row.get("birthdate"),
                role_id=row.get("role_id"),
                role_name=row.get("role_name"),
                timezone=None,
                is_active=bool(row["is_active"]) if row.get("is_active") is not None else None,
            )  
        else :
            return UserItem(
                user_id=row.get("user_id"),
                table_used="user",
                username=row.get("username"),
                email=row.get("email"),
                full_name=None,
                phone=row.get("phone"),
                birthdate=row.get("birthdate"),
                role_id=row.get("role_id"),
                role_name=row.get("role_name"),
                timezone=None,
                is_active=None
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")
    finally:
        try:
            cur.close()
            cnx.close()
        except Exception:
            pass

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")

    try:
        cur = cnx.cursor(dictionary=True)
        table_name, pk = find_user_location(cur, user_id)
        if not table_name:
            raise HTTPException(status_code=404, detail="User not found.")

        cur.execute(f"DELETE FROM {table_name} WHERE {pk}=%s", (user_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found.")
        cnx.commit()
        return {"detail": "User deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        cnx.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")
    finally:
        try:
            cur.close()
            cnx.close()
        except Exception:
            pass

# --------------Update--------------
# @app.put("/api/users/{user_id}", response_model=UserItem)
# def update_user(user_id: int, payload: UpdateUserRequest):
#     try:
#         cnx = get_conn()
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")

#     try:
#         cur = cnx.cursor(dictionary=True)

#         has_users = table_exists(cur, "users")
#         has_user = table_exists(cur, "user")
#         if not has_users and not has_user:
#             raise HTTPException(status_code=500, detail="No suitable user table found. Expected 'users' or 'user'.")
#         table_name = "users" if has_users else "user"

#         cur.execute(f"SELECT user_id FROM {table_name} WHERE user_id=%s", (user_id,))
#         if not cur.fetchone():
#             raise HTTPException(status_code=404, detail="User not found.")
        
#         if payload.email:
#             cur.execute(
#                 f"SELECT 1 FROM {table_name} WHERE email=%s AND user_id<>%s LIMIT 1",
#                 (payload.email, user_id),
#             )
#             if cur.fetchone():
#                 raise HTTPException(status_code=400, detail="Email already in use by another user.")

#         updates = []
#         params = []

#         if payload.full_name is not None:
#             updates.append("full_name=%s")
#             params.append(payload.full_name)
#         if payload.email is not None:
#             updates.append("email=%s")
#             params.append(payload.email)
#         if payload.timezone is not None:
#             updates.append("timezone=%s")
#             params.append(payload.timezone)
#         if payload.is_active is not None:
#             updates.append("is_active=%s")
#             params.append(1 if payload.is_active else 0)
#         if payload.role_id is not None:
#             updates.append("role_id=%s")
#             params.append(payload.role_id)
#         if payload.password:
#             import hashlib
#             pwd_hash = hashlib.sha256(payload.password.encode("utf-8")).hexdigest()
#             updates.append("password_hash=%s")
#             params.append(pwd_hash)

#         if not updates:
#             raise HTTPException(status_code=400, detail="No fields to update.")

#         params.append(user_id)
#         cur.execute(f"UPDATE {table_name} SET {', '.join(updates)} WHERE user_id=%s", tuple(params))
#         cnx.commit()

#         cur.execute(
#             f"SELECT user_id, full_name, user_name, email, is_active, role_id FROM {table_name} WHERE user_id=%s",
#             (user_id,),
#         )
#         row = cur.fetchone()
#         return UserItem(**row)

#     except mysql.connector.IntegrityError as e:
#         cnx.rollback()
#         raise HTTPException(status_code=400, detail=f"Integrity error: {e.msg}")
#     except Exception as e:
#         cnx.rollback()
#         raise HTTPException(status_code=500, detail=f"Update failed: {e}")
#     finally:
#         cur.close()
#         cnx.close()



# app --reload --port 8000
