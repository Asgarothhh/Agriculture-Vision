DEFAULT_API_URL = "http://localhost:8000"

ARCHITECTURES = ("yolo", "segformer")

YOLO_CLASSES = {
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
}

SEGFORMER_CLASSES = {
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
}

CROP_CLASSES = [
    "wheat",
    "corn",
    "soybean",
    "sunflower",
    "rapeseed",
    "barley",
    "oat",
    "rice",
    "potato",
    "sugar_beet",
]

CLASSIFICATION_THRESHOLD = 0.6
DEFAULT_SEGMENTATION_THRESHOLD = 0.4
