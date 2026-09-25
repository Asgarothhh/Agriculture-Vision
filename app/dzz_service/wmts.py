from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

SUPPORTED_CRS = (
    "EPSG:3857",
    "EPSG:900913",
    "EPSG:3785",
    "EPSG:4326",
    "CRS:84",
)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _first(el: ET.Element, *names: str) -> ET.Element | None:
    wanted = set(names)
    for child in el:
        if _local(child.tag) in wanted:
            return child
    return None


def _first_text(el: ET.Element, *names: str) -> str:
    node = _first(el, *names)
    return _text(node)


def _findall_local(el: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in el.iter() if _local(child.tag) == name]


def _crs_supported(crs: str) -> bool:
    value = (crs or "").upper()
    return any(token in value for token in SUPPORTED_CRS)


def _well_known(matrix_id: str) -> str:
    raw = matrix_id or ""
    for name in (
        "GoogleMapsCompatible",
        "GoogleCRS84Quad",
        "WebMercatorQuad",
        "default028mm",
        "EPSG:3857",
        "EPSG:4326",
    ):
        if name.lower() in raw.lower():
            return name
    return raw


def parse_wmts_capabilities(xml_text: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {"layers": [], "tileMatrixSets": [], "tileUrlTemplate": "", "suggested": None}

    matrices: list[dict[str, Any]] = []
    matrix_index: dict[str, dict[str, Any]] = {}
    for node in _findall_local(root, "TileMatrixSet"):
        ident = _first_text(node, "Identifier")
        if not ident:
            continue
        crs = _first_text(node, "SupportedCRS")
        item = {
            "id": ident,
            "crs": crs,
            "wellKnown": _well_known(ident),
            "supported": _crs_supported(crs) or _crs_supported(ident),
        }
        matrices.append(item)
        matrix_index[ident] = item

    layers: list[dict[str, Any]] = []
    tile_url_template = ""
    for layer in _findall_local(root, "Layer"):
        ident = _first_text(layer, "Identifier")
        if not ident:
            continue
        title = _first_text(layer, "Title") or ident
        styles: list[str] = []
        default_style = "default"
        for style in layer.iter():
            if _local(style.tag) != "Style":
                continue
            style_id = _first_text(style, "Identifier") or "default"
            styles.append(style_id)
            if (style.attrib.get("isDefault") or "").lower() in {"true", "1"}:
                default_style = style_id
        if not styles:
            styles = ["default"]
        matrix_ids: list[str] = []
        for link in layer.iter():
            if _local(link.tag) == "TileMatrixSet" and _text(link):
                matrix_ids.append(_text(link))
            elif _local(link.tag) == "TileMatrixSetLink":
                nested = _first_text(link, "TileMatrixSet")
                if nested:
                    matrix_ids.append(nested)
        resource_url = ""
        for url_node in layer.iter():
            if _local(url_node.tag) != "ResourceURL":
                continue
            if (url_node.attrib.get("resourceType") or "tile") == "tile":
                resource_url = url_node.attrib.get("template") or ""
                if resource_url:
                    break
        if resource_url and not tile_url_template:
            tile_url_template = resource_url
        layers.append(
            {
                "id": ident,
                "title": title,
                "styles": list(dict.fromkeys(styles)),
                "defaultStyle": default_style if default_style in styles else styles[0],
                "tileMatrixSets": list(dict.fromkeys(matrix_ids)),
                "resourceUrl": resource_url,
            }
        )

    suggested = pick_suggested_wmts(layers, matrices, tile_url_template)
    return {
        "layers": layers,
        "tileMatrixSets": matrices,
        "tileUrlTemplate": tile_url_template,
        "suggested": suggested,
        "matrixIndex": matrix_index,
    }


def pick_suggested_wmts(
    layers: list[dict[str, Any]],
    matrices: list[dict[str, Any]],
    tile_url_template: str,
) -> dict[str, Any] | None:
    if not layers:
        return None
    layer = layers[0]
    matrix_ids = layer.get("tileMatrixSets") or [item["id"] for item in matrices]
    preferred = None
    fallback = None
    by_id = {item["id"]: item for item in matrices}
    for matrix_id in matrix_ids:
        item = by_id.get(matrix_id) or {
            "id": matrix_id,
            "wellKnown": _well_known(matrix_id),
            "supported": True,
            "reachable": True,
        }
        if item.get("reachable") is False:
            continue
        if not item.get("supported", True):
            continue
        if item.get("wellKnown") == "GoogleMapsCompatible":
            fallback = fallback or item
            continue
        preferred = item
        break
    matrix = preferred or fallback or (by_id.get(matrix_ids[0]) if matrix_ids else None)
    if matrix is None:
        return None
    style = layer.get("defaultStyle") or (layer.get("styles") or ["default"])[0]
    template = layer.get("resourceUrl") or tile_url_template
    filled = fill_wmts_template(template, layer["id"], matrix["id"], style)
    return {
        "layer": layer["id"],
        "matrix": matrix["id"],
        "style": style,
        "tileUrlTemplate": filled,
        "wellKnown": matrix.get("wellKnown") or matrix["id"],
    }


def fill_wmts_template(template: str, layer: str, matrix: str, style: str) -> str:
    if not template:
        return ""
    return (
        template.replace("{Layer}", layer)
        .replace("{TileMatrixSet}", matrix)
        .replace("{Style}", style)
    )


def parse_wmts_layers_flat(xml_text: str) -> list[dict[str, str]]:
    catalog = parse_wmts_capabilities(xml_text)
    items: list[dict[str, str]] = []
    for layer in catalog["layers"]:
        matrix = (layer.get("tileMatrixSets") or [""])[0]
        style = layer.get("defaultStyle") or "default"
        items.append({"layer": layer["id"], "tilematrix": matrix, "style": style})
    return items


def resolve_wmts_capabilities_url(url: str) -> str:
    raw = (url or "").strip()
    raw = re.sub(r"/tile/\{[^/]+\}/\{[^/]+\}/\{[^/]+\}.*$", "", raw, flags=re.IGNORECASE)
    raw = raw.rstrip("/")
    if re.search(r"WMTSCapabilities\.xml", raw, re.IGNORECASE):
        return re.sub(r"(\?.*)?$", "", raw)
    if re.search(r"/ImageServer$", raw, re.IGNORECASE):
        return f"{raw}/WMTS/1.0.0/WMTSCapabilities.xml"
    if re.search(r"/MapServer$", raw, re.IGNORECASE):
        return f"{raw}/WMTS/1.0.0/WMTSCapabilities.xml"
    if raw.lower().endswith("/wmts"):
        return f"{raw}/1.0.0/WMTSCapabilities.xml"
    return f"{raw}/WMTS/1.0.0/WMTSCapabilities.xml"
