import os
import argparse
import mlflow
import mlflow.pytorch
import torch
import torch.nn as nn


def setup_mlflow_environment():
    """Настройка переменных окружения для подключения к MinIO и MLflow Server."""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadminpassword")
    os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000")

    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment("Agriculture-Vision-Baseline")


def train_pipeline(args):
    setup_mlflow_environment()

    # Старт эксперимента в MLflow
    with mlflow.start_run(run_name=args.run_name):
        params = {
            "learning_rate": args.lr,
            "batch_size": args.batch_size,
            "epochs": args.epochs,
            "architecture": args.architecture,
            "optimizer": "AdamW"
        }
        mlflow.log_params(params)
        mlflow.set_tags({"developer": args.developer, "task": "segmentation"})

    # 2. Логирование метаданных и конфигураций
    model_config = {
        "input_shape": [3, 512, 512],
        "classes": ["background", "crop", "weed"],
        "device": "cuda" if torch.cuda.is_available() else "cpu"
    }
    mlflow.log_dict(model_config, "config/model_config.json")

    # Имитация простейшей модели
    model = nn.Sequential(nn.Linear(10, 5), nn.ReLU(), nn.Linear(5, 3))

    # 3. Цикл обучения с логированием метрик по эпохам
    for epoch in range(1, args.epochs + 1):
        # Пример получения метрик
        train_loss = 0.5 / epoch
        val_iou = 0.5 + (0.04 * epoch)
        val_acc = 0.80 + (0.015 * epoch)

        # Логирование метрик с привязкой к шагу (step)
        mlflow.log_metrics({
            "train_loss": train_loss,
            "val_iou": min(val_iou, 0.95),
            "val_accuracy": min(val_acc, 0.99)
        }, step=epoch)

    # 4. Сохранение весов и самой модели в MLflow / MinIO S3
    mlflow.pytorch.log_model(
        pytorch_model=model,
        artifact_path="model",
        registered_model_name="Agriculture_SegFormer_Model"
    )

    print(f"Эксперимент '{args.run_name}' успешно записан в MLflow!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLflow Training Template")
    parser.add_argument("--run_name", type=str, default="baseline_run")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--architecture", type=str, default="SegFormer-B0")
    parser.add_argument("--developer", type=str, default="ML-Team")

    args = parser.parse_args()
    train_pipeline(args)