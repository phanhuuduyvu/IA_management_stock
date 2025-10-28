import os
import re
import uuid
import time
import hashlib
import jwt  # PyJWT
from datetime import timezone
from datetime import date, datetime, timedelta
from typing import List, Optional, Literal, Any, Dict, Tuple 
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime, timezone

from dotenv import load_dotenv
import mysql.connector
from mysql.connector import errors as mysql_errors
from fastapi import FastAPI, HTTPException, Depends, status, Header, Request
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

print("Now UTC:", datetime.now(timezone.utc).isoformat())

# ------------------ Load env ------------------
load_dotenv()
DB_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("MYSQL_PORT", "3306"))
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASS = os.getenv("MYSQL_PASSWORD", "")
DB_NAME = os.getenv("MYSQL_DB", "FoodCo_Management")

# JWT env
JWT_SECRET = os.getenv("JWT_SECRET", "change_me_super_secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))

# ------------------ Regex -----------------
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,30}$")
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# ------------------ FastAPI -----------------

app = FastAPI(title="FoodCo API", version="1.0")

# CORS: allow frontend at these origins to call API
origins = [
    "http://localhost:5500",      # VS Code Live Server
    "http://127.0.0.1:5500",
    # add more if you run on other ports:
    # "http://localhost:3000",
    # "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------ Schemas -----------------
class CreateUserRequest(BaseModel):
    username: str = Field(..., description="Username 3-30 a-zA-Z0-9_")
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
            raise ValueError("Invalid username format (must be 3-30 alphanumeric/underscore)")
        return v

    @validator("email")
    def _check_email(cls, v: str):
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("Invalid email format")
        return v

class UserItem(BaseModel):
    user_id: int
    table_used: Literal["users", "user"]
    username: str
    email: str
    phone: Optional[str] = None
    birthdate: Optional[date] = None
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    is_active: Optional[bool] = None


class CreateUserResponse(BaseModel):
    user_id: int
    table_used: Literal["users", "user"]
    username: str
    email: str

# ---- Auth Schemas ----
class LoginRequest(BaseModel):
    identifier: str = Field(..., description="username hoặc email")
    password: str = Field(..., min_length=8)

class TokenPairResponse(BaseModel):
    token_type: Literal["bearer"] = "bearer"
    access_token: str
    access_expires_at: int  # epoch seconds
    refresh_token: str
    refresh_expires_at: int  # epoch seconds

class RefreshRequest(BaseModel):
    refresh_token: str

class LogoutResponse(BaseModel):
    detail: str

# ------------------ DB Helpers -----------------
def _now() -> datetime:
    now = datetime.now(timezone.utc)
    print("[DEBUG] UTC now:", now.isoformat())
    return now

def decode_token(token: str) -> dict:
    try:
        now = datetime.now(timezone.utc).timestamp()
        print("[DEBUG] Server time (epoch):", now)
        return jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            leeway=60  
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        print("[JWT Decode Error]", str(e))
        raise HTTPException(status_code=401, detail="Invalid token")
def get_conn():
    return mysql.connector.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME
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

def get_users_pk(cur) -> str:
    # Prefer common column names
    cols = get_columns(cur, "users")
    if "UserID" in cols: return "UserID"
    if "user_id" in cols: return "user_id"
    if "id" in cols: return "id"
    # Thử đọc từ khóa chính
    cur.execute("SHOW KEYS FROM `users` WHERE Key_name='PRIMARY'")
    row = cur.fetchone()
    if row:
        if isinstance(row, dict):
            return row.get("Column_name", "UserID")
        elif len(row) >= 5:
            return row[4]
    return "UserID"

def find_user_location(cur, user_id: int) -> Tuple[str, str]:
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
            f"u.{pk} AS user_id",
            "u.UserName AS username" if "UserName" in cols else "u.Username AS username",
            "u.Email AS email",
        ]
        if "PhoneNumber" in cols: select_fields.append("u.PhoneNumber AS phone")
        if "BirthDate" in cols: select_fields.append("u.BirthDate AS birthdate")
        if "RoleID" in cols: select_fields.append("u.RoleID AS role_id")
        if "IsActive" in cols: select_fields.append("u.IsActive AS is_active")
        role_join = ""
        if "RoleID" in cols and table_exists(cur, "roles"):
            role_join = " LEFT JOIN roles r ON u.RoleID = r.RoleID "
            select_fields.append("r.RoleName AS role_name")
        sql = f"SELECT {', '.join(select_fields)} FROM `users` u {role_join} WHERE u.`{pk}`=%s LIMIT 1"
        cur.execute(sql, (user_id,))
        return cur.fetchone()

    if table_name == "user":
        cols = get_columns(cur, "user")
        uname_col = "Username" if "Username" in cols else "UserName"
        phone_col = "Phonenumber" if "Phonenumber" in cols else ("PhoneNumber" if "PhoneNumber" in cols else None)
        fields = [
            "u.UserID AS user_id",
            f"u.{uname_col} AS username",
            "u.Email AS email",
        ]
        if phone_col: fields.append(f"u.{phone_col} AS phone")
        if "Birthdate" in cols: fields.append("u.Birthdate AS birthdate")
        if "RoleID" in cols: fields.append("u.RoleID AS role_id")
        role_join = ""
        if "RoleID" in cols and table_exists(cur, "roles"):
            role_join = " LEFT JOIN roles r ON u.RoleID = r.RoleID "
            fields.append("r.RoleName AS role_name")
        if "IsActive" in cols: fields.append("u.IsActive AS is_active")
        sql = f"SELECT {', '.join(fields)} FROM `user` u {role_join} WHERE u.`UserID`=%s LIMIT 1"
        cur.execute(sql, (user_id,))
        return cur.fetchone()

    return None

def username_or_email_exists(cur, table_name: str, username: str, email: str, exclude_pk: Optional[Tuple[str, int]] = None) -> bool:
    if table_name == "users":
        pk = get_users_pk(cur)
        q = f"SELECT 1 FROM `users` WHERE (UserName=%s OR Email=%s)"
        params = [username, email]
        if exclude_pk:
            q += f" AND `{pk}`<>%s"
            params.append(exclude_pk[1])
        q += " LIMIT 1"
        cur.execute(q, tuple(params))
        return cur.fetchone() is not None

    if table_name == "user":
        cols = get_columns(cur, "user")
        uname_col = "Username" if "Username" in cols else "UserName"
        pk = "UserID"
        q = f"SELECT 1 FROM `user` WHERE ({uname_col}=%s OR Email=%s)"
        params = [username, email]
        if exclude_pk:
            q += f" AND `{pk}`<>%s"
            params.append(exclude_pk[1])
        q += " LIMIT 1"
        cur.execute(q, tuple(params))
        return cur.fetchone() is not None

    return False

# ------------------ Password helpers -----------------
def hash_sha256(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()

def verify_password(plain: str, hashed: str) -> bool:
    return hash_sha256(plain) == hashed

# ------------------ CRUD APIs -----------------
@app.get("/api/users", response_model=List[UserItem])
def list_user():
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")

    results: List[UserItem] = []
    try:
        cur = cnx.cursor(dictionary=True)
        has_users = table_exists(cur, "users")
        has_user = table_exists(cur, "user")
        if not has_users and not has_user:
            raise HTTPException(status_code=500, detail="No suitable user table found. Expected 'users' or 'user'.")

        if has_users:
            cols = get_columns(cur, "users")
            pk = get_users_pk(cur)
            select_fields = [
                f"u.{pk} AS user_id",
                "u.UserName AS username" if "UserName" in cols else "u.Username AS username",
                "u.Email AS email",
            ]
            if "PhoneNumber" in cols: select_fields.append("u.PhoneNumber AS phone")
            if "BirthDate" in cols: select_fields.append("u.BirthDate AS birthdate")
            if "RoleID" in cols: select_fields.append("u.RoleID AS role_id")
            if "IsActive" in cols: select_fields.append("u.IsActive AS is_active")
            role_join = ""
            if "RoleID" in cols and table_exists(cur, "roles"):
                role_join = " LEFT JOIN roles r ON u.RoleID = r.RoleID "
                select_fields.append("r.RoleName AS role_name")
            sql_users = f"SELECT {', '.join(select_fields)} FROM `users` u {role_join} ORDER BY u.`{pk}` ASC"
            cur.execute(sql_users)
            for row in cur.fetchall():
                results.append(
                    UserItem(
                        user_id=row.get("user_id"),
                        table_used="users",
                        username=row.get("username"),
                        email=row.get("email"),
                        phone=row.get("phone"),
                        birthdate=row.get("birthdate"),
                        role_id=row.get("role_id"),
                        role_name=row.get("role_name"),
                        is_active=bool(row["is_active"]) if row.get("is_active") is not None else None,
                    )
                )

        if has_user:
            cols = get_columns(cur, "user")
            uname_col = "Username" if "Username" in cols else "UserName"
            phone_col = "Phonenumber" if "Phonenumber" in cols else ("PhoneNumber" if "PhoneNumber" in cols else None)
            select_fields = [
                "u.UserID AS user_id",
                f"u.{uname_col} AS username",
                "u.Email AS email",
            ]
            if phone_col: select_fields.append(f"u.{phone_col} AS phone")
            if "Birthdate" in cols: select_fields.append("u.Birthdate AS birthdate")
            if "RoleID" in cols: select_fields.append("u.RoleID AS role_id")
            if "IsActive" in cols: select_fields.append("u.IsActive AS is_active")
            role_join = ""
            if "RoleID" in cols and table_exists(cur, "roles"):
                role_join = " LEFT JOIN roles r ON u.RoleID = r.RoleID "
                select_fields.append("r.RoleName AS role_name")
            sql_user = f"SELECT {', '.join(select_fields)} FROM `user` u {role_join} ORDER BY u.`UserID` ASC"
            cur.execute(sql_user)
            for row in cur.fetchall():
                results.append(
                    UserItem(
                        user_id=row.get("user_id"),
                        table_used="user",
                        username=row.get("username"),
                        email=row.get("email"),
                        phone=row.get("phone"),
                        birthdate=row.get("birthdate"),
                        role_id=row.get("role_id"),
                        role_name=row.get("role_name"),
                        is_active=bool(row["is_active"]) if row.get("is_active") is not None else None,
                    )
                )

        return results

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    finally:
        try:
            cur.close(); cnx.close()
        except Exception:
            pass

@app.post("/api/users", response_model=CreateUserResponse, status_code=201)
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

        # Unique check
        if username_or_email_exists(cur, table_name, payload.username, payload.email):
            raise HTTPException(status_code=400, detail="Username or email already exists.")

        pwd_hash = hash_sha256(payload.password)
        is_active = 1 if (payload.is_active is None or payload.is_active) else 0

        if table_name == "users":
            sql = """
                INSERT INTO `users` (UserName, PhoneNumber, Email, PasswordHash, BirthDate, RoleID, IsActive)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cur.execute(sql, (
                payload.username, payload.phone, payload.email, pwd_hash,
                payload.birthdate, payload.role_id, is_active
            ))
        else:
            cols = get_columns(cur, "user")
            uname_col = "Username" if "Username" in cols else "UserName"
            phone_col = "Phonenumber" if "Phonenumber" in cols else ("PhoneNumber" if "PhoneNumber" in cols else None)
            # Build dynamic insert
            fields = [uname_col, "Email", "PasswordHash"]
            values = [payload.username, payload.email, pwd_hash]
            if phone_col: fields.append(phone_col); values.append(payload.phone)
            if "Birthdate" in cols: fields.append("Birthdate"); values.append(payload.birthdate)
            if "RoleID" in cols: fields.append("RoleID"); values.append(payload.role_id)
            if "IsActive" in cols: fields.append("IsActive"); values.append(is_active)

            placeholders = ", ".join(["%s"] * len(values))
            sql = f"INSERT INTO `user` ({', '.join(fields)}) VALUES ({placeholders})"
            cur.execute(sql, tuple(values))

        cnx.commit()
        new_id = cur.lastrowid
        return CreateUserResponse(user_id=new_id, table_used=table_name, username=payload.username, email=payload.email)

    except mysql.connector.IntegrityError as e:
        cnx.rollback()
        raise HTTPException(status_code=400, detail=f"Integrity error: {e.msg}")
    except Exception as e:
        cnx.rollback()
        raise HTTPException(status_code=500, detail=f"Create failed: {e}")
    finally:
        try:
            cur.close(); cnx.close()
        except Exception:
            pass

@app.get("/api/users/{user_id}", response_model=UserItem)
def get_user_by_id(user_id: int):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")

    try:
        cur = cnx.cursor(dictionary=True)
        table_name, pk = find_user_location(cur, user_id)
        row = get_user_item(cur, table_name, pk if table_name == "users" else "UserID", user_id)
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        return UserItem(
            user_id=row.get("user_id"),
            table_used=table_name,
            username=row.get("username"),
            email=row.get("email"),
            phone=row.get("phone"),
            birthdate=row.get("birthdate"),
            role_id=row.get("role_id"),
            role_name=row.get("role_name"),
            is_active=bool(row["is_active"]) if row.get("is_active") is not None else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    finally:
        try:
            cur.close(); cnx.close()
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

        if username_or_email_exists(cur, table_name, payload.username, payload.email, exclude_pk=(pk, user_id)):
            raise HTTPException(status_code=400, detail="Username or email already exists.")

        pwd_hash = hash_sha256(payload.password)
        is_active = 1 if (payload.is_active is None or payload.is_active) else 0

        if table_name == "users":
            sql = f"""
                UPDATE `users`
                SET UserName=%s, PhoneNumber=%s, Email=%s, PasswordHash=%s, BirthDate=%s, RoleID=%s, IsActive=%s
                WHERE `{pk}`=%s
            """
            cur.execute(sql, (
                payload.username, payload.phone, payload.email, pwd_hash,
                payload.birthdate, payload.role_id, is_active, user_id
            ))
        else:
            cols = get_columns(cur, "user")
            uname_col = "Username" if "Username" in cols else "UserName"
            phone_col = "Phonenumber" if "Phonenumber" in cols else ("PhoneNumber" if "PhoneNumber" in cols else None)

            sets = [f"{uname_col}=%s", "Email=%s", "PasswordHash=%s"]
            values = [payload.username, payload.email, pwd_hash]
            if phone_col: sets.append(f"{phone_col}=%s"); values.append(payload.phone)
            if "Birthdate" in cols: sets.append("Birthdate=%s"); values.append(payload.birthdate)
            if "RoleID" in cols: sets.append("RoleID=%s"); values.append(payload.role_id)
            if "IsActive" in cols: sets.append("IsActive=%s"); values.append(is_active)

            sql = f"UPDATE `user` SET {', '.join(sets)} WHERE `UserID`=%s"
            values.append(user_id)
            cur.execute(sql, tuple(values))

        cnx.commit()
        # return latest
        row = get_user_item(cur, table_name, pk if table_name == "users" else "UserID", user_id)
        if not row:
            raise HTTPException(status_code=404, detail="User not found after update.")
        return UserItem(
            user_id=row.get("user_id"),
            table_used=table_name,
            username=row.get("username"),
            email=row.get("email"),
            phone=row.get("phone"),
            birthdate=row.get("birthdate"),
            role_id=row.get("role_id"),
            role_name=row.get("role_name"),
            is_active=bool(row["is_active"]) if row.get("is_active") is not None else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")
    finally:
        try:
            cur.close(); cnx.close()
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
        cur.execute(f"DELETE FROM `{table_name}` WHERE `{pk}`=%s", (user_id,))
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
            cur.close(); cnx.close()
        except Exception:
            pass

# ------------------ Auth (JWT) -----------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

REVOKED_JTI: set[str] = set()

def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())

def create_token(sub: str, kind: Literal["access", "refresh"], extra_claims: Dict[str, Any] | None = None) -> Tuple[str, int, str]:
    jti = str(uuid.uuid4())
    iat = _now()
    exp = iat + (timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES) if kind == "access" else timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    payload: Dict[str, Any] = {
        "sub": sub,
        "jti": jti,
        "iat": _epoch(iat),
        "exp": _epoch(exp),
        "type": kind,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, _epoch(exp), jti

# ====== Middleware: log headers ======
class LogHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        print("[DEBUG] Incoming Request Headers:", dict(request.headers))
        response = await call_next(request)
        return response

app.add_middleware(LogHeadersMiddleware)


def ensure_not_revoked(jti: str):
    if jti in REVOKED_JTI:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    

def _fetch_user_by_username_or_email(cur, identifier: str) -> Optional[dict]:
    # Try `users`
    if table_exists(cur, "users"):
        cur.execute(
            """
            SELECT 
              u.UserID        AS user_id,
              u.UserName      AS username,
              u.Email         AS email,
              u.PhoneNumber   AS phone,
              u.PasswordHash  AS password_hash,
              u.RoleID        AS role_id,
              u.IsActive      AS is_active
            FROM users u
            WHERE u.UserName=%s OR u.Email=%s
            LIMIT 1
            """,
            (identifier, identifier),
        )
        row = cur.fetchone()
        if row:
            return row
    # Try `user`
    if table_exists(cur, "user"):
        cols = get_columns(cur, "user")
        uname_col = "Username" if "Username" in cols else "UserName"
        phone_col = "Phonenumber" if "Phonenumber" in cols else ("PhoneNumber" if "PhoneNumber" in cols else None)
        cur.execute(
            f"""
            SELECT 
              u.UserID        AS user_id,
              u.{uname_col}   AS username,
              u.Email         AS email,
              {f'u.{phone_col} AS phone,' if phone_col else 'NULL AS phone,'}
              u.PasswordHash  AS password_hash,
              u.RoleID        AS role_id,
              { 'u.IsActive' if 'IsActive' in cols else 'NULL'} AS is_active
            FROM user u
            WHERE u.{uname_col}=%s OR u.Email=%s
            LIMIT 1
            """,
            (identifier, identifier),
        )
        row = cur.fetchone()
        if row:
            return row
    return None

def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    print("[DEBUG] Access token:", token)
    payload = decode_token(token)
    print("[DEBUG] Payload:", payload)
    ensure_not_revoked(payload.get("jti", ""))
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an access token")
    user_id = payload.get("sub")
    # verify still exists
    try:
        cnx = get_conn()
        cur = cnx.cursor(dictionary=True)
        table_name, pk = find_user_location(cur, int(user_id))
        row = get_user_item(cur, table_name, pk if table_name == "users" else "UserID", int(user_id))
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return {"user_id": row["user_id"], "username": row["username"], "email": row["email"]}
    finally:
        try:
            cur.close(); cnx.close()
        except Exception:
            pass

@app.post("/api/auth/login", response_model=TokenPairResponse)
def login(payload: LoginRequest):
    try:
        cnx = get_conn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connect failed: {e}")
    try:
        cur = cnx.cursor(dictionary=True)
        u = _fetch_user_by_username_or_email(cur, payload.identifier)
        if not u:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if u.get("is_active") is not None and int(u["is_active"]) == 0:
            raise HTTPException(status_code=403, detail="User is inactive")
        if not verify_password(payload.password, u["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        access_token, access_exp, _ = create_token(sub=str(u["user_id"]), kind="access", extra_claims={"username": u["username"]})
        refresh_token, refresh_exp, _ = create_token(sub=str(u["user_id"]), kind="refresh")
        return TokenPairResponse(
            access_token=access_token,
            access_expires_at=access_exp,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_exp,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {e}")
    finally:
        try:
            cur.close(); cnx.close()
        except Exception:
            pass

@app.post("/api/auth/refresh", response_model=TokenPairResponse)
def refresh_token(payload: RefreshRequest):
    data = decode_token(payload.refresh_token)
    ensure_not_revoked(data.get("jti", ""))
    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    user_id = data.get("sub")
    # rotate refresh → revoke old refresh
    old_jti = data.get("jti")
    if old_jti:
        REVOKED_JTI.add(old_jti)
    # verify user still active
    try:
        cnx = get_conn()
        cur = cnx.cursor(dictionary=True)
        table_name, pk = find_user_location(cur, int(user_id))
        row = get_user_item(cur, table_name, pk if table_name == "users" else "UserID", int(user_id))
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        username = row["username"]
    finally:
        try:
            cur.close(); cnx.close()
        except Exception:
            pass
    access_token, access_exp, _ = create_token(sub=str(user_id), kind="access", extra_claims={"username": username})
    new_refresh, refresh_exp, _ = create_token(sub=str(user_id), kind="refresh")
    return TokenPairResponse(
        access_token=access_token,
        access_expires_at=access_exp,
        refresh_token=new_refresh,
        refresh_expires_at=refresh_exp,
    )

@app.post("/api/auth/logout", response_model=LogoutResponse)
def logout(authorization: str = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=400, detail="Missing Bearer token in Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    data = decode_token(token)
    jti = data.get("jti")
    if not jti:
        raise HTTPException(status_code=400, detail="Token missing jti")
    REVOKED_JTI.add(jti)
    return LogoutResponse(detail="Logged out (access token revoked).")

@app.post("/api/auth/logout_refresh", response_model=LogoutResponse)
def logout_refresh(payload: RefreshRequest):
    data = decode_token(payload.refresh_token)
    if data.get("type") != "refresh":
        raise HTTPException(status_code=400, detail="Not a refresh token")
    jti = data.get("jti")
    if jti:
        REVOKED_JTI.add(jti)
    return LogoutResponse(detail="Refresh token revoked.")

@app.get("/api/me", response_model=UserItem)
def read_me(current=Depends(get_current_user)):
    try:
        cnx = get_conn()
        cur = cnx.cursor(dictionary=True)
        table_name, pk = find_user_location(cur, int(current["user_id"]))
        row = get_user_item(cur, table_name, pk if table_name == "users" else "UserID", int(current["user_id"]))
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return UserItem(
            user_id=row.get("user_id"),
            table_used=table_name,
            username=row.get("username"),
            email=row.get("email"),
            phone=row.get("phone"),
            birthdate=row.get("birthdate"),
            role_id=row.get("role_id"),
            role_name=row.get("role_name"),
            is_active=bool(row["is_active"]) if row.get("is_active") is not None else None,
        )
    finally:
        try:
            cur.close(); cnx.close()
        except Exception:
            pass

# ------------------ Dev runner ------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("user:app", host="0.0.0.0", port=8000, reload=True)
