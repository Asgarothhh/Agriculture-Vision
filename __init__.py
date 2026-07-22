def _ensure_user_site_packages() -> None:
  """Подключает ~/.local/.../site-packages (opencv и др. для Python QGIS)."""
  import site
  import sys
  from pathlib import Path

  candidates = []
  try:
    candidates.append(Path(site.getusersitepackages()))
  except Exception:
    pass
  candidates.append(Path.home() / ".local" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")

  for path in candidates:
    if path.is_dir():
      path_str = str(path)
      if path_str not in sys.path:
        sys.path.insert(0, path_str)


def classFactory(iface):
  _ensure_user_site_packages()
  from .agriculture_vision_plugin import AgricultureVisionPlugin
  return AgricultureVisionPlugin(iface)
