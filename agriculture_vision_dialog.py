"""Главное окно плагина Agriculture Vision (remote API / mock)."""

from __future__ import annotations

from qgis.core import Qgis, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .api_client import AgricultureVisionClient, ApiError
from .constants import (
    ARCHITECTURES,
    CLASSIFICATION_THRESHOLD,
    DEFAULT_API_URL,
    DEFAULT_SEGMENTATION_THRESHOLD,
)
from .layer_utils import (
    add_segmentation_results,
    geometry_to_png_base64,
    list_polygon_layers,
    list_raster_layers,
    raster_layer_to_png_bytes,
)
from .mock_client import MockAgricultureVisionClient


class ApiSegmentWorker(QThread):
    """Фоновый вызов POST /api/v1/segmentation/segment."""

    progress = pyqtSignal(int)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, client, image_bytes: bytes, architecture: str, threshold: float):
        super().__init__()
        self.client = client
        self.image_bytes = image_bytes
        self.architecture = architecture
        self.threshold = threshold

    def run(self):
        try:
            self.progress.emit(10)
            result = self.client.segment(
                self.image_bytes,
                architecture=self.architecture,
                threshold=self.threshold,
            )
            self.progress.emit(100)
            self.finished.emit(result)
        except ApiError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f"Ошибка сегментации: {exc}")


class AgricultureVisionDialog(QDialog):
    CHANNEL = "Agriculture Vision"

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Agriculture Vision")
        self.resize(680, 540)
        self.worker = None

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_connection_tab(), "Подключение")
        self.tabs.addTab(self._build_segmentation_tab(), "Сегментация")
        self.tabs.addTab(self._build_classification_tab(), "Классификация полей")
        self.tabs.addTab(self._build_log_tab(), "Журнал событий")

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        QgsProject.instance().layersAdded.connect(self._refresh_layer_lists)
        QgsProject.instance().layersRemoved.connect(self._refresh_layer_lists)
        self._refresh_layer_lists()
        self._update_mode_hint()

    def _client(self):
        if self.mock_checkbox.isChecked():
            return MockAgricultureVisionClient()
        return AgricultureVisionClient(self.url_edit.text().strip() or DEFAULT_API_URL)

    def _log(self, message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Info):
        prefix = f"[{level.name}] " if hasattr(level, "name") else ""
        self.log_area.append(f"{prefix}{message}")
        QgsMessageLog.logMessage(message, self.CHANNEL, level)

    def _refresh_layer_lists(self):
        current_raster = self.raster_combo.currentData()
        current_class_raster = self.class_raster_combo.currentData()
        current_poly = self.polygon_combo.currentData()

        self.raster_combo.clear()
        self.class_raster_combo.clear()
        for layer in list_raster_layers():
            self.raster_combo.addItem(layer.name(), layer)
            self.class_raster_combo.addItem(layer.name(), layer)

        self.polygon_combo.clear()
        for layer in list_polygon_layers():
            self.polygon_combo.addItem(layer.name(), layer)

        self._restore_combo(self.raster_combo, current_raster)
        self._restore_combo(self.class_raster_combo, current_class_raster)
        self._restore_combo(self.polygon_combo, current_poly)

    @staticmethod
    def _restore_combo(combo: QComboBox, layer) -> None:
        if layer is None:
            return
        for i in range(combo.count()):
            if combo.itemData(i) == layer:
                combo.setCurrentIndex(i)
                return

    def _update_mode_hint(self):
        if self.mock_checkbox.isChecked():
            self.mode_label.setText("Режим: MOCK (локальные заглушки, backend не нужен)")
            self.mode_label.setStyleSheet("color: #b36b00; font-weight: bold;")
        else:
            url = self.url_edit.text().strip() or DEFAULT_API_URL
            self.mode_label.setText(f"Режим: REMOTE API → {url}")
            self.mode_label.setStyleSheet("color: #1b7a3d; font-weight: bold;")

    # --- UI ---

    def _build_connection_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.url_edit = QLineEdit(DEFAULT_API_URL)
        self.url_edit.setPlaceholderText("http://192.168.1.5:8000")
        self.url_edit.textChanged.connect(self._update_mode_hint)

        self.mock_checkbox = QCheckBox("Использовать заглушки (mock)")
        self.mock_checkbox.setChecked(False)
        self.mock_checkbox.stateChanged.connect(self._update_mode_hint)

        form.addRow("URL API:", self.url_edit)
        form.addRow("", self.mock_checkbox)
        layout.addLayout(form)

        self.mode_label = QLabel()
        layout.addWidget(self.mode_label)

        btn_row = QHBoxLayout()
        self.health_btn = QPushButton("Проверить связь")
        self.health_btn.clicked.connect(self._on_health_clicked)
        btn_row.addWidget(self.health_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.health_status = QTextEdit()
        self.health_status.setReadOnly(True)
        self.health_status.setMaximumHeight(180)
        layout.addWidget(self.health_status)
        layout.addStretch(1)
        return widget

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

        self.segment_btn = QPushButton("Запустить сегментацию")
        self.segment_btn.setStyleSheet(
            "background-color: #2b8cbe; color: white; font-weight: bold; padding: 6px;"
        )
        self.segment_btn.clicked.connect(self._on_segment_clicked)

        self.segment_progress = QProgressBar()
        self.segment_progress.setVisible(False)

        layout.addRow("Целевой растр (RGB/NIR):", self.raster_combo)
        layout.addRow("Нейросетевая модель:", self.architecture_combo)
        layout.addRow("Порог уверенности:", self.threshold_spin)
        layout.addRow(self.segment_progress)
        layout.addRow(self.segment_btn)
        return widget

    def _build_classification_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.class_raster_combo = QComboBox()
        self.polygon_combo = QComboBox()
        form.addRow("Растр для вырезки:", self.class_raster_combo)
        form.addRow("Векторный слой полей:", self.polygon_combo)
        layout.addLayout(form)

        self.classify_btn = QPushButton("Определить культуру")
        self.classify_btn.clicked.connect(self._on_classify_clicked)
        layout.addWidget(self.classify_btn)

        self.classification_summary = QLabel("Ожидание запуска классификации...")
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

    # --- Actions ---

    def _on_health_clicked(self):
        client = self._client()
        lines = []
        try:
            root = client.check_connection()
            lines.append(f"GET / → {root}")
            seg = client.health_segmentation()
            lines.append(f"segmentation/health → {seg}")
            clf = client.health_classification()
            lines.append(f"classification/health → {clf}")
            self.health_status.setPlainText("\n".join(lines))
            self._log("Проверка связи: OK", Qgis.MessageLevel.Success)
            QMessageBox.information(self, "Связь", "Backend доступен.")
        except Exception as exc:
            self.health_status.setPlainText(str(exc))
            self._log(f"Проверка связи: FAIL — {exc}", Qgis.MessageLevel.Critical)
            QMessageBox.critical(self, "Нет связи", str(exc))

    def _on_segment_clicked(self):
        raster_layer = self.raster_combo.currentData()
        if not raster_layer:
            QMessageBox.warning(self, "Внимание", "Выберите растровый слой.")
            return

        arch = self.architecture_combo.currentText()
        thresh = self.threshold_spin.value()
        client = self._client()
        mode = "mock" if self.mock_checkbox.isChecked() else client.base_url

        self.segment_btn.setEnabled(False)
        self.segment_progress.setVisible(True)
        self.segment_progress.setValue(0)
        self._log(
            f"Сегментация {arch} → {mode}, слой '{raster_layer.name()}', "
            f"threshold={thresh:.2f}..."
        )

        try:
            image_bytes = raster_layer_to_png_bytes(raster_layer)
        except Exception as exc:
            self._on_segment_error(f"Не удалось экспортировать растр: {exc}")
            return

        self.worker = ApiSegmentWorker(client, image_bytes, arch, thresh)
        self.worker.progress.connect(self.segment_progress.setValue)
        self.worker.error.connect(self._on_segment_error)
        self.worker.finished.connect(
            lambda res, t=thresh: self._on_segment_success(res, raster_layer, arch, t)
        )
        self.worker.start()

    def _on_segment_error(self, err_msg: str):
        self._log(f"Ошибка сегментации: {err_msg}", Qgis.MessageLevel.Critical)
        QMessageBox.critical(self, "Ошибка анализа", err_msg)
        self.segment_btn.setEnabled(True)
        self.segment_progress.setVisible(False)

    def _on_segment_success(self, result: dict, raster_layer, arch: str, requested_thr: float):
        try:
            if not result.get("ok", True):
                raise RuntimeError(result.get("error") or result)

            metrics = result.get("metrics") or {}
            used_thr = metrics.get("threshold_used")
            if used_thr is not None:
                self._log(f"threshold запрошен={requested_thr:.3f}, backend threshold_used={float(used_thr):.3f}")
                if abs(float(used_thr) - float(requested_thr)) > 0.05:
                    self._log(
                        "Backend проигнорировал порог UI (threshold_used ≠ запрошенный). "
                        "Для segformer это известный баг API.",
                        Qgis.MessageLevel.Warning,
                    )

            n_det = len(result.get("detections") or [])
            has_nav = bool((result.get("navigable") or {}).get("valid"))
            if arch == "yolo" and n_det == 0:
                msg = (
                    f"YOLO: 0 детекций при threshold={requested_thr:.2f}. "
                    "Попробуйте снизить порог (например 0.10–0.20)."
                )
                self._log(msg, Qgis.MessageLevel.Warning)
                QMessageBox.information(self, "Пустой результат", msg)
                return
            if arch == "segformer" and not has_nav and "navigable" in result:
                msg = f"SegFormer: нет валидного полигона при threshold={requested_thr:.2f}."
                self._log(msg, Qgis.MessageLevel.Warning)
                QMessageBox.information(self, "Пустой результат", msg)
                return

            layer = add_segmentation_results(
                raster_layer,
                result,
                arch,
                group_name="Agriculture Vision",
                threshold=requested_thr,
            )
            feat_count = layer.featureCount() if layer is not None else 0
            self._log(
                f"Сегментация {arch} готова: объектов={feat_count}, слой добавлен.",
                Qgis.MessageLevel.Success,
            )
            self.iface.messageBar().pushMessage(
                "Agriculture Vision",
                f"Готово ({arch}, thr={requested_thr:.2f}, objs={feat_count})",
                Qgis.MessageLevel.Success,
            )
        except Exception as exc:
            self._log(f"Ошибка отрисовки: {exc}", Qgis.MessageLevel.Critical)
            QMessageBox.critical(self, "Ошибка", str(exc))
        finally:
            self.segment_btn.setEnabled(True)
            self.segment_progress.setVisible(False)

    def _on_classify_clicked(self):
        poly_layer = self.polygon_combo.currentData()
        raster_layer = self.class_raster_combo.currentData()
        if not poly_layer:
            QMessageBox.warning(self, "Внимание", "Выберите векторный слой полей.")
            return
        if not raster_layer:
            QMessageBox.warning(self, "Внимание", "Выберите растр для вырезки полигона.")
            return

        features = list(poly_layer.getFeatures())
        if not features:
            QMessageBox.warning(self, "Внимание", "В слое нет объектов.")
            return

        # Берём выбранный feature, иначе первый
        selected = poly_layer.selectedFeatures()
        feature = selected[0] if selected else features[0]

        self.classify_btn.setEnabled(False)
        self._log(f"Классификация feature {feature.id()} слоя '{poly_layer.name()}'...")

        try:
            image_b64 = geometry_to_png_base64(feature.geometry(), raster_layer)
            client = self._client()
            res = client.classify_crop(image_b64, threshold=CLASSIFICATION_THRESHOLD)

            predicted = res.get("predicted_class") or res.get("predicted") or "?"
            confidence = float(res.get("confidence") or 0)
            requires_review = res.get("requires_review", confidence < CLASSIFICATION_THRESHOLD)

            self.classification_table.setRowCount(0)
            for item in res.get("probabilities", []):
                row = self.classification_table.rowCount()
                self.classification_table.insertRow(row)
                self.classification_table.setItem(row, 0, QTableWidgetItem(str(item.get("crop_class", ""))))
                self.classification_table.setItem(
                    row, 1, QTableWidgetItem(f"{float(item.get('probability', 0)):.2%}")
                )

            review_str = " ⚠️ (требует проверки)" if requires_review else ""
            self.classification_summary.setText(
                f"Результат: <b>{predicted}</b> ({confidence:.1%}){review_str}"
            )
            self._log(f"Классификация: {predicted} ({confidence:.2%})")
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
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(1000)
        super().closeEvent(event)
