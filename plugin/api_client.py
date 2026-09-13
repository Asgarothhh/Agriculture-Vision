"""HTTP-клиент к Agriculture Vision API (FastAPI backend из папки web/)."""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AgricultureVisionClient:
    def __init__(self, base_url: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_json(self, path: str, params: dict | None = None) -> dict[str, Any]:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(detail or str(exc), exc.code) from exc
        except URLError as exc:
            raise ApiError(f"Не удалось подключиться к API: {exc.reason}") from exc

    def _post_json(self, path: str, payload: dict) -> dict[str, Any]:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(detail or str(exc), exc.code) from exc
        except URLError as exc:
            raise ApiError(f"Не удалось подключиться к API: {exc.reason}") from exc

    def _post_multipart(
        self,
        path: str,
        fields: dict[str, str],
        file_field: str,
        file_bytes: bytes,
        filename: str = "image.png",
    ) -> dict[str, Any]:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        boundary = f"----QGISBoundary{uuid.uuid4().hex}"
        body_parts: list[bytes] = []

        for name, value in fields.items():
            body_parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode("utf-8")
            )

        body_parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode("utf-8")
        )
        body_parts.append(file_bytes)
        body_parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(body_parts)

        request = Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(detail or str(exc), exc.code) from exc
        except URLError as exc:
            raise ApiError(f"Не удалось подключиться к API: {exc.reason}") from exc

    def check_connection(self) -> dict[str, Any]:
        return self._get_json("/")

    def health_segmentation(self, architecture: str = "all") -> dict[str, Any]:
        return self._get_json(
            "/api/v1/segmentation/health",
            {"architecture": architecture},
        )

    def health_classification(self) -> dict[str, Any]:
        return self._get_json("/api/v1/classification/health")

    def segment(
        self,
        image_bytes: bytes,
        architecture: str = "yolo",
        threshold: float | None = None,
        tta: bool = False,
        include_geojson: bool = False,
    ) -> dict[str, Any]:
        query: dict[str, str] = {
            "architecture": architecture,
            "include_mask_png": "false",
            "include_geojson": "true" if include_geojson else "false",
        }
        if threshold is not None:
            query["threshold"] = str(threshold)
        if architecture == "yolo" and tta:
            query["tta"] = "true"

        path = f"/api/v1/segmentation/segment?{urlencode(query)}"
        return self._post_multipart(path, {}, "file", image_bytes)

    def classify_crop(
        self,
        image_base64: str,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"image_base64": image_base64}
        if threshold is not None:
            payload["threshold"] = threshold
        return self._post_json("/api/v1/classification/classify", payload)

    def list_models(self) -> dict[str, Any]:
        return self._get_json("/api/v1/segmentation/models")
