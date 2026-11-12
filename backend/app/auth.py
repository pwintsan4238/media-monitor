import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request

from .config import settings

COOKIE = "mm_token"


def verify_login(username: str, password: str) -> bool:
    if not settings.admin_password_hash or username != settings.admin_username:
        return False
    try:
        return bcrypt.checkpw(password.encode(), settings.admin_password_hash.encode())
    except ValueError:
        return False


def make_token(username: str) -> str:
    exp = int(time.time()) + settings.jwt_expire_hours * 3600
    return jwt.encode({"sub": username, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def current_user(request: Request) -> str:
    token = request.cookies.get(COOKIE)
    if not token:
        h = request.headers.get("authorization", "")
        token = h[7:] if h.lower().startswith("bearer ") else None
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session")


Authed = Depends(current_user)
