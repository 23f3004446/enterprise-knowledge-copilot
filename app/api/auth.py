from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_current_user_from_credentials, verify_password
from app.db.database import get_db
from app.db.models import User
from app.schemas.schemas import LoginRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = create_access_token(
        {"sub": str(user.id), "user_id": user.id, "username": user.username, "email": user.email, "role": user.role}
    )
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user_from_credentials)) -> UserResponse:
    return UserResponse(
        id=int(current_user.get("user_id", current_user["sub"])),
        email=current_user.get("email", "unknown@example.com"),
        username=current_user.get("username", "unknown"),
        role=current_user.get("role", "EMPLOYEE"),
    )
