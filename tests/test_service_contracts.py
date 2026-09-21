from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class ServiceContractTests(TestCase):
    def test_fastapi_monolith_entrypoints(self) -> None:
        for relative_path in (
            "app/main.py",
            "app/core/config.py",
            "app/users_service/routers/auth.py",
            "app/tasks_service/routers/tasks.py",
            "app/layers_service/routers/layers.py",
            "app/dzz_service/routers/proxy.py",
            "app/ml_service/runtime.py",
            "deploy/docker-compose.yml",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_no_ml_server_package(self) -> None:
        self.assertFalse((ROOT / "ml_server").exists())

    def test_auth_routes_match_spec(self) -> None:
        source = (ROOT / "app/users_service/routers/auth.py").read_text(encoding="utf-8")
        for route in (
            "/register",
            "/login",
            "/refresh",
            "/logout",
            "/password-reset/request",
            "/password-reset/confirm",
        ):
            self.assertIn(route, source)
