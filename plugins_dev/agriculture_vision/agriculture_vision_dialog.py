"""Главное окно автономного плагина Agriculture Vision."""

from __future__ import annotations

from qgis.core import Qgis, QgsMessageLog, QgsProject
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QProgressBar
)

from .constants import ARCHITECTURES, CLASSIFICATION_THRESHOLD, DEFAULT_SEGMENTATION_THRESHOLD
from .layer_utils import add_segmentation_results, list_polygon_layers, list_raster_layers
from .local_processor import LocalSegmentationWorker, LocalClassifier

class AgricultureVisionDialog(QDialog):
    CHANNEL = "Agriculture Vision"

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Agriculture Vision (Локальный модуль)")
        self.resize(650, 500)

        # Компоновка вкладок
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_segmentation_tab(), "Сегментация")
        self.tabs.addTab(self._build_classification_tab(), "Классификация полей")
        self.tabs.addTab(self._build_log_tab(), "Журнал событий")

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        # Автовызов обновления списков слоев при их изменении в QGIS
        QgsProject.instance().layersAdded.connect(self._refresh_layer_lists)
        QgsProject.instance().layersRemoved.connect(self._refresh_layer_lists)
        self._refresh_layer_lists()

    def _log(self, message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Info):
        prefix = f"[{level.name}] " if hasattr(level, 'name') else ""
        self.log_area.append(f"{prefix}{message}")
        QgsMessageLog.logMessage(message, self.CHANNEL, level)

    def _refresh_layer_lists(self):
        """Обновление выпадающих списков слоев из текущего проекта QGIS"""
        self.raster_combo.clear()
        for layer in list_raster_layers():
            self.raster_combo.addItem(layer.name(), layer)

        self.polygon_combo.clear()
        for layer in list_polygon_layers():
            self.polygon_combo.addItem(layer.name(), layer)

    # --- СБОРКА ИНТЕРФЕЙСА ---

    def _build_segmentation_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        self.raster_combo = QComboBox()
        self.architecture_combo = QComboBox()
        self.architecture_combo.addItems(ARCHITECTURES)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(DEFAULT_SEGMENTATION_THRESHOLD)

        self.segment_btn = QPushButton("Запустить локальный анализ растра")
        self.segment_btn.setStyleSheet("background-color: #2b8cbe; color: white; font-weight: bold; padding: 6px;")
        self.segment_btn.clicked.connect(self._on_segment_clicked)

        self.segment_progress = QProgressBar()
        self.segment_progress.setVisible(False)

        layout.addRow("Целевой растр (RGB/NIR):", self.raster_combo)
        layout.addRow("Нейросетевая модель:", self.architecture_combo)
        layout.addRow("Порог уверенности (Confidence):", self.threshold_spin)
        layout.addRow(self.segment_progress)
        layout.addRow(self.segment_btn)
        return widget

    def _build_classification_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form_layout = QFormLayout()
        self.polygon_combo = QComboBox()
        form_layout.addRow("Выбрать векторный слой полей:", self.polygon_combo)
        layout.addLayout(form_layout)

        self.classify_btn = QPushButton("Определить культуру (Локально)")
        self.classify_btn.clicked.connect(self._on_classify_clicked)
        layout.addWidget(self.classify_btn)

        self.classification_summary = QLabel("Ожидание запуска классификации...")
        self.classification_summary.setStyleSheet("font-size: 13px; color: #333;")
        layout.addWidget(self.classification_summary)

        self.classification_table = QTableWidget(0, 2)
        self.classification_table.setHorizontalHeaderLabels(["Сельхозкультура", "Вероятность"])
        layout.addWidget(self.classification_table)
        return widget

    def _build_log_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)
        return widget

    # --- ЛОГИКА НАЖАТИЯ КНОПОК ---

    def _on_segment_clicked(self):
        raster_layer = self.raster_combo.currentData()
        if not raster_layer:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, выберите или загрузите растровый слой в QGIS.")
            return

        arch = self.architecture_combo.currentText()
        thresh = self.threshold_spin.value()

        self.segment_btn.setEnabled(False)
        self.segment_progress.setVisible(True)
        self.segment_progress.setValue(0)

        self._log(f"Запуск локального инференса {arch.upper()} для слоя '{raster_layer.name()}'...")

        # Инициализируем фоновый поток
        self.worker = LocalSegmentationWorker(raster_layer, arch, thresh)
        self.worker.progress.connect(self.segment_progress.setValue)
        self.worker.error.connect(self._on_segment_error)
        self.worker.finished.connect(lambda res: self._on_segment_success(res, raster_layer, arch))
        self.worker.start()

    def _on_segment_error(self, err_msg):
        self._log(f"Ошибка вычислений: {err_msg}", Qgis.MessageLevel.Critical)
        QMessageBox.critical(self, "Ошибка анализа", err_msg)
        self.segment_btn.setEnabled(True)
        self.segment_progress.setVisible(False)

    def _on_segment_success(self, result, raster_layer, arch):
        try:
            # Вызываем твой инструмент отрисовки слоев
            add_segmentation_results(raster_layer, result, arch, group_name="AgroGIS Результаты")
            self._log(f"Локальная сегментация {arch} успешно завершена. Слои добавлены в проект.", Qgis.MessageLevel.Success)
            self.iface.messageBar().pushMessage("AgroGIS", "Анализ завершен, векторные слои построены!", Qgis.MessageLevel.Success)
        except Exception as e:
            self._log(f"Ошибка отрисовки результатов: {e}", Qgis.MessageLevel.Critical)
        finally:
            self.segment_btn.setEnabled(True)
            self.segment_progress.setVisible(False)

    def _on_classify_clicked(self):
        poly_layer = self.polygon_combo.currentData()
        if not poly_layer:
            QMessageBox.warning(self, "Внимание", "Не выбран векторный слой полей для классификации.")
            return

        self._log(f"Запуск локальной классификации культур для слоя '{poly_layer.name()}'...")
        self.classify_btn.setEnabled(False)

        try:
            # Запускаем локальный анализ
            res = LocalClassifier.classify(poly_layer.id())

            predicted = res["predicted"]
            confidence = res["confidence"]
            requires_review = confidence < CLASSIFICATION_THRESHOLD

            # Заполнение таблицы результатов
            self.classification_table.setRowCount(0)
            for item in res["probabilities"]:
                row = self.classification_table.rowCount()
                self.classification_table.insertRow(row)
                self.classification_table.setItem(row, 0, QTableWidgetItem(item["crop_class"]))
                self.classification_table.setItem(row, 1, QTableWidgetItem(f"{item['probability']:.2%}"))

            review_str = " ⚠️ (Требует проверки!)" if requires_review else ""
            self.classification_summary.setText(
                f"Результат: <b>{predicted}</b> ({confidence:.1%}){review_str}"
            )

            self._log(f"Успешно классифицировано: {predicted} ({confidence:.2%})")

        except Exception as exc:
            self._log(f"Ошибка классификации: {exc}", Qgis.MessageLevel.Critical)
            QMessageBox.critical(self, "Ошибка", str(exc))
        finally:
            self.classify_btn.setEnabled(True)

    def closeEvent(self, event):
        try:
            QgsProject.instance().layersAdded.disconnect(self._refresh_layer_lists)
            QgsProject.instance().layersRemoved.disconnect(self._refresh_layer_lists)
        except TypeError:
            pass
        super().closeEvent(event)
