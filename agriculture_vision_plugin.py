from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication

from .agriculture_vision_dialog import AgricultureVisionDialog


class AgricultureVisionPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        self.action = QAction(
            QIcon(),
            QApplication.translate("AgricultureVision", "Agriculture Vision…"),
            self.iface.mainWindow(),
        )
        self.action.setObjectName("AgricultureVision")
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(
            QApplication.translate("AgricultureVision", "Agriculture Vision"),
            self.action,
        )

    def unload(self):
        self.iface.removePluginMenu(
            QApplication.translate("AgricultureVision", "Agriculture Vision"),
            self.action,
        )
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None

    def run(self):
        if self.dialog is None:
            self.dialog = AgricultureVisionDialog(self.iface, self.iface.mainWindow())
            self.dialog.finished.connect(self._on_dialog_closed)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _on_dialog_closed(self):
        self.dialog = None
