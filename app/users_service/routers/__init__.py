from app.users_service.routers.auth import router as auth_router
from app.users_service.routers.profile import router as profile_router

__all__ = ["auth_router", "profile_router"]
