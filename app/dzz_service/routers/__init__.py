from app.dzz_service.routers.connection import router as connection_router
from app.dzz_service.routers.proxy import router as proxy_router
from app.dzz_service.routers.wmts import router as wmts_router

__all__ = ["connection_router", "proxy_router", "wmts_router"]
