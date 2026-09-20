from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Settings:
    model_architecture: str = "yolo"
    max_concurrent_inferences: int = 1
    default_confidence_threshold: float = 0.4
    default_iou_threshold: float = 0.5
    inference_image_size: int = 640

    yolo_weights_path: str = "config/yolo_best.pt"
    yolo_fallback_weights: str = "yolo11m-seg.pt"
    yolo_class_names: dict[int, str] = field(default_factory=lambda: {
        0: "field",
        1: "double_plant",
        2: "drydown",
        3: "endrow",
        4: "nutrient_deficiency",
        5: "planter_skip",
        6: "storm_damage",
        7: "water",
        8: "waterway",
        9: "weed_cluster",
    })

    segformer_weights_path: str = "config/segformer_best.pt"
    segformer_pretrained_model: str = "nvidia/segformer-b5-finetuned-ade-640-640"
    segformer_num_labels: int = 10
    segformer_class_names: dict[int, str] = field(default_factory=lambda: {
        0: "background",
        1: "field",
        2: "double_plant",
        3: "drydown",
        4: "endrow",
        5: "nutrient_deficiency",
        6: "planter_skip",
        7: "storm_damage",
        8: "water",
        9: "waterway",
        10: "weed_cluster",
    })

    classification_confidence_threshold: float = 0.6
    crop_classes: list[str] = field(default_factory=lambda: [
        "wheat", "corn", "soybean", "sunflower", "rapeseed",
        "barley", "oat", "rice", "potato", "sugar_beet",
    ])
    crop_classification_model: str = "crop_classifier_v1"

    model_version: str = "1.0.0"
    cached_val_metrics: dict[str, Any] | None = field(default_factory=lambda: {
        "mAP_0.5": 0.732,
        "mAP_0.5_0.95": 0.514,
        "precision": 0.768,
        "recall": 0.701,
    })
