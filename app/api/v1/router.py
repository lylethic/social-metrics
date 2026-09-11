from fastapi import APIRouter
from app.api.v1.endpoints import auth, platforms

api_router = APIRouter()

# Include Auth Endpoints
api_router.include_router(auth.router)

# Include Platform Endpoints
api_router.include_router(platforms.router)

