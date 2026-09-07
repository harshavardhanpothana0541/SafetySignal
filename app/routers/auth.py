# app/routers/auth.py
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.database import SessionLocal
from app import models
from app.services.auth_service import auth_service

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# --- Request Schemas ---
class RegisterRequest(BaseModel):
    username: str
    password: str
    badge_number: str

class RegisterResponderRequest(BaseModel):
    username: str
    password: str
    phone_number: Optional[str] = "+919391774539"
    badge_number: Optional[str] = None
    role: Optional[str] = "responder"

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenRequest(BaseModel):
    user_id: str
    role: str  # "victim", "responder", or "admin"

class UserProfilePayload(BaseModel):
    phone_number: str
    full_name: Optional[str] = "Citizen"
    building: Optional[str] = None
    floor: Optional[str] = None
    flat_no: Optional[str] = None
    landmark: Optional[str] = None
    lat: Optional[float] = 16.5062
    lng: Optional[float] = 80.6480
    ice_phone: Optional[str] = None


def seed_default_accounts(db):
    """Ensures default demo credentials exist in the database."""
    if not db.query(models.User).filter(models.User.username == "responder1").first():
        db.add(models.User(
            username="responder1",
            hashed_password=auth_service.get_password_hash("password123"),
            full_name="Officer Rao (EMT)",
            badge_number="EMT-8841",
            role="responder",
            karma_score=120,
            strikes=0,
            is_suspended=False
        ))
    if not db.query(models.User).filter(models.User.username == "admin").first():
        db.add(models.User(
            username="admin",
            hashed_password=auth_service.get_password_hash("admin123"),
            full_name="CAD Dispatch Admin",
            role="admin",
            badge_number="CAD-001"
        ))
    db.commit()


@router.post("/token")
def generate_client_token(req: TokenRequest):
    """
    Issues signed JWTs for guest victims, anonymous clients, and UI role switches.
    """
    if req.role not in ["victim", "responder", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role specified")

    token = auth_service.create_access_token({
        "sub": req.user_id,
        "role": req.role
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": req.user_id,
        "role": req.role
    }


@router.post("/register-responder")
def register_new_responder(req: RegisterResponderRequest):
    """
    Allows voluntary responder onboarding directly from UI modal with automatic login token.
    """
    db = SessionLocal()
    try:
        clean_username = req.username.strip()
        existing_user = db.query(models.User).filter(models.User.username == clean_username).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already registered. Please sign in.")

        badge = req.badge_number or f"VOL-{clean_username[:4].upper()}-99"
        new_user = models.User(
            username=clean_username,
            hashed_password=auth_service.get_password_hash(req.password),
            phone_number=req.phone_number,
            badge_number=badge,
            full_name=clean_username,
            role="responder",
            karma_score=100,
            strikes=0,
            is_suspended=False
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        token = auth_service.create_access_token({
            "sub": new_user.username,
            "badge_number": new_user.badge_number,
            "role": new_user.role
        })

        return {
            "status": "success",
            "message": "Responder successfully registered!",
            "access_token": token,
            "token_type": "bearer",
            "username": new_user.username,
            "badge_number": new_user.badge_number,
            "role": new_user.role,
            "karma_score": new_user.karma_score
        }
    finally:
        db.close()


@router.post("/register")
def register_responder(req: RegisterRequest):
    db = SessionLocal()
    try:
        existing_user = db.query(models.User).filter(models.User.username == req.username).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already registered")

        new_user = models.User(
            username=req.username,
            hashed_password=auth_service.get_password_hash(req.password),
            badge_number=req.badge_number,
            role="responder",
            is_suspended=False,
            karma_score=100
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        token = auth_service.create_access_token({
            "sub": new_user.username,
            "badge_number": new_user.badge_number,
            "role": new_user.role
        })
        return {
            "access_token": token,
            "token_type": "bearer",
            "badge_number": new_user.badge_number,
            "role": new_user.role
        }
    finally:
        db.close()


@router.post("/login")
def login_responder(req: LoginRequest):
    db = SessionLocal()
    try:
        seed_default_accounts(db)
        user = db.query(models.User).filter(models.User.username == req.username).first()
        
        if not user or not auth_service.verify_password(req.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        if getattr(user, "is_suspended", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account suspended due to unfulfilled dispatches."
            )

        token = auth_service.create_access_token({
            "sub": user.username,
            "badge_number": user.badge_number,
            "role": user.role
        })
        return {
            "access_token": token,
            "token_type": "bearer",
            "username": user.username,
            "badge_number": user.badge_number,
            "role": user.role,
            "karma_score": getattr(user, "karma_score", 100)
        }
    finally:
        db.close()


@router.post("/register-profile")
def register_or_update_profile(payload: UserProfilePayload):
    """Registers citizen base address mapped to phone for telephony triggers."""
    db = SessionLocal()
    try:
        clean_phone = payload.phone_number.strip()
        user = db.query(models.User).filter(models.User.phone_number == clean_phone).first()

        if not user:
            user = models.User(
                username=f"user_{clean_phone[-4:]}",
                hashed_password=auth_service.get_password_hash("guest_pass"),
                phone_number=clean_phone,
                full_name=payload.full_name,
                role="victim"
            )
            db.add(user)

        user.default_building = payload.building
        user.default_floor = payload.floor
        user.default_flat_no = payload.flat_no
        user.default_landmark = payload.landmark
        user.default_lat = payload.lat
        user.default_lng = payload.lng
        user.ice_contact_phone = payload.ice_phone

        db.commit()
        db.refresh(user)

        return {
            "status": "success",
            "message": f"Profile mapped for {clean_phone}",
            "base_location": f"{user.default_building}, Flat {user.default_flat_no}"
        }
    finally:
        db.close()