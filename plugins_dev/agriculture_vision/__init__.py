def classFactory(iface):
  from .agriculture_vision_plugin import AgricultureVisionPlugin
  return AgricultureVisionPlugin(iface)
