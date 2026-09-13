"""Structural contract tests for the public backend API.

These tests intentionally avoid loading ML dependencies.  They guard the URL
contracts while services are moved independently.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ServiceContractTests(unittest.TestCase):
    def test_services_have_independent_entrypoints(self) -> None:
        for relative_path in (
            "app/api_gateway/server.js",
            "app/users_service/server.js",
            "app/segmentation_service/app.py",
            "app/ml_core/train_seg.py",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_gateway_preserves_public_route_prefixes(self) -> None:
        source = (ROOT / "app/api_gateway/server.js").read_text(encoding="utf-8")
        self.assertIn("'/api'", source)
        self.assertIn("'/api/v1/segmentation'", source)
        self.assertIn("'/api/v1/classification'", source)

    def test_users_service_preserves_auth_routes(self) -> None:
        source = (ROOT / "app/users_service/server.js").read_text(encoding="utf-8")
        for route in (
            "/api/register",
            "/api/login",
            "/api/logout",
            "/api/me",
            "/api/profile",
            "/api/account",
        ):
            self.assertIn(route, source)

    def test_segmentation_service_preserves_routes(self) -> None:
        source = (ROOT / "app/segmentation_service/app.py").read_text(encoding="utf-8")
        for route in (
            "/health",
            "/api/v1/segmentation/health",
            "/v1/segment",
            "/api/v1/segmentation/segment",
            "/v1/jobs/{job_id}",
        ):
            self.assertIn(route, source)


if __name__ == "__main__":
    unittest.main()
