"""Обучение SegFormer-B4 на Agriculture-Vision (4 канала, boundary)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from tqdm import tqdm
from transformers import SegformerConfig, SegformerForSemanticSegmentation

from field_detecter.agvision_augment import build_train_transform
from field_detecter.agvision_dataset import AgVisionDataset, collate_segformer_batch
from field_detecter.config_loader import load_config, project_root
from field_detecter.metrics import (
    compare_to_tz_targets,
    evaluate_masks_masked,
    save_metrics_report,
)


def _amp_autocast(enabled: bool):
    if not enabled:
        from contextlib import nullcontext

        return nullcontext()
    if hasattr(torch.amp, "autocast"):
        return torch.amp.autocast("cuda")
    return torch.cuda.amp.autocast()


def _amp_scaler(enabled: bool):
    if not enabled:
        return None
    if hasattr(torch.amp, "GradScaler"):
        return torch.amp.GradScaler("cuda")
    return torch.cuda.amp.GradScaler()


def _first_patch_proj(model: SegformerForSemanticSegmentation) -> torch.nn.Conv2d:
    """Первый patch embedding (transformers >= 4.4: segformer.stages.0.patch_embeddings.proj)."""
    seg = model.segformer
    if hasattr(seg, "encoder") and hasattr(seg.encoder, "patch_embed"):
        return seg.encoder.patch_embed[0].proj
    if hasattr(seg, "stages"):
        return seg.stages[0].patch_embeddings.proj
    raise AttributeError("Cannot find SegFormer patch embedding module")


def expand_segformer_to_4ch(model: SegformerForSemanticSegmentation) -> None:
    """Заменяем первый Conv2d 3→4 канала (NIR init из R)."""
    old = _first_patch_proj(model)
    if old.in_channels == 4:
        return
    new_conv = torch.nn.Conv2d(
        4,
        old.out_channels,
        kernel_size=old.kernel_size,
        stride=old.stride,
        padding=old.padding,
        bias=old.bias is not None,
    )
    with torch.no_grad():
        # NIR — среднее RGB (лучше, чем только R, для 4-канального входа)
        new_conv.weight[:, 0] = old.weight.mean(dim=1)
        new_conv.weight[:, 1] = old.weight[:, 0]
        new_conv.weight[:, 2] = old.weight[:, 1]
        new_conv.weight[:, 3] = old.weight[:, 2]
        if old.bias is not None:
            new_conv.bias.copy_(old.bias)
    if hasattr(model.segformer, "stages"):
        model.segformer.stages[0].patch_embeddings.proj = new_conv
    else:
        model.segformer.encoder.patch_embed[0].proj = new_conv


def load_segformer_binary(model_id: str, num_labels: int = 2) -> SegformerForSemanticSegmentation:
    """SegFormer с 2 классами без конфликта id2label (ADE=150)."""
    config = SegformerConfig.from_pretrained(model_id)
    config.num_labels = num_labels
    config.id2label = {str(i): ("background", "boundary")[i] for i in range(num_labels)}
    config.label2id = {v: k for k, v in config.id2label.items()}
    return SegformerForSemanticSegmentation.from_pretrained(
        model_id,
        config=config,
        ignore_mismatched_sizes=True,
    )


class Segformer4ChWrapper(torch.nn.Module):
    """SegFormer с 4-канальным входом (NIR,R,G,B)."""

    def __init__(self, model_id: str, num_labels: int = 2) -> None:
        super().__init__()
        self.model = load_segformer_binary(model_id, num_labels=num_labels)
        expand_segformer_to_4ch(self.model)

    def forward(self, pixel_values: torch.Tensor, labels: torch.Tensor | None = None):
        return self.model(pixel_values=pixel_values, labels=labels)


def masked_ce_dice_loss(
    logits: torch.Tensor,
    labels: torch.Tensor,
    valid_mask: torch.Tensor,
    *,
    fg_weight: float = 3.0,
    dice_weight: float = 0.4,
    label_smoothing: float = 0.0,
) -> torch.Tensor:
    # logits: B,C,H,W — upsample to labels size
    if logits.shape[-2:] != labels.shape[-2:]:
        logits = F.interpolate(
            logits, size=labels.shape[-2:], mode="bilinear", align_corners=False
        )
    weights = torch.tensor([1.0, fg_weight], device=logits.device)
    ce = F.cross_entropy(
        logits, labels, weight=weights, reduction="none", label_smoothing=label_smoothing
    )
    vm = valid_mask.bool()
    ce = ce[vm]
    if ce.numel() == 0:
        return ce.sum()
    ce_loss = ce.mean()

    probs = F.softmax(logits, dim=1)[:, 1]
    tgt = labels.float()
    vm_f = vm.float()
    inter = (probs * tgt * vm_f).sum()
    denom = (probs * vm_f).sum() + (tgt * vm_f).sum()
    dice = 1.0 - (2 * inter + 1e-6) / (denom + 1e-6)
    return (1 - dice_weight) * ce_loss + dice_weight * dice


@torch.no_grad()
def predict_logits(
    model: Segformer4ChWrapper,
    batch: dict[str, torch.Tensor],
    device: torch.device,
    *,
    tta: bool = False,
) -> np.ndarray:
    model.eval()
    x = batch["pixel_values"].to(device)
    out = model(x)
    logits = out.logits
    if logits.shape[-2:] != x.shape[-2:]:
        logits = F.interpolate(
            logits, size=x.shape[-2:], mode="bilinear", align_corners=False
        )
    if not tta:
        return logits.argmax(dim=1).cpu().numpy()

    preds = []
    for flip in ((), (2,), (3,), (2, 3)):
        xi = x if not flip else x.flip(flip)
        lo = model(xi).logits
        if lo.shape[-2:] != x.shape[-2:]:
            lo = F.interpolate(lo, size=x.shape[-2:], mode="bilinear", align_corners=False)
        lo = lo if not flip else lo.flip(flip)
        preds.append(lo.softmax(dim=1))
    mean = torch.stack(preds).mean(0)
    return mean.argmax(dim=1).cpu().numpy()


def run_validation(
    model: Segformer4ChWrapper,
    loader: DataLoader,
    device: torch.device,
    *,
    threshold: float = 0.5,
    tta: bool = True,
    max_batches: int | None = None,
) -> dict[str, float]:
    model.eval()
    pairs = []
    for bi, batch in enumerate(tqdm(loader, desc="val", leave=False)):
        if max_batches is not None and bi >= max_batches:
            break
        x = batch["pixel_values"].to(device)
        vm = batch["valid_mask"].numpy()
        with torch.no_grad():
            out = model(x)
            logits = out.logits
            if logits.shape[-2:] != x.shape[-2:]:
                logits = F.interpolate(
                    logits, size=x.shape[-2:], mode="bilinear", align_corners=False
                )
            if tta:
                probs_list = []
                for flip in ((), (2,), (3,)):
                    xi = x if not flip else x.flip(flip)
                    lo = model(xi).logits
                    if lo.shape[-2:] != x.shape[-2:]:
                        lo = F.interpolate(
                            lo, size=x.shape[-2:], mode="bilinear", align_corners=False
                        )
                    lo = lo if not flip else lo.flip(flip)
                    probs_list.append(lo.softmax(dim=1))
                prob = torch.stack(probs_list).mean(0)[:, 1].cpu().numpy()
            else:
                prob = logits.softmax(dim=1)[:, 1].cpu().numpy()
        pred = (prob >= threshold).astype(np.uint8)
        labels = batch["labels"].numpy()
        for i in range(pred.shape[0]):
            pairs.append((pred[i], labels[i], vm[i]))
    return evaluate_masks_masked(pairs)


def _backup_checkpoint(path: Path) -> None:
    if path.is_file():
        bak = path.with_name(path.stem + "_backup" + path.suffix)
        import shutil

        shutil.copy2(path, bak)
        print(f"Backup: {bak}")


def _log_batch_nir_stats(batch: dict[str, torch.Tensor]) -> None:
    x = batch["pixel_values"]
    nir = x[:, 0]
    rgb = x[:, 1:4]
    print(
        f"  NIR mean={nir.mean():.3f} std={nir.std():.3f} | "
        f"RGB mean={rgb.mean():.3f} | 4ch active"
    )


def train(
    config: dict[str, Any],
    *,
    data_root: Path | None = None,
) -> Path:
    root = project_root()
    data_cfg = config["data"]
    seg_cfg = config["segmentation"]
    data_root = Path(data_root or root / data_cfg["root"])
    version_dir = data_cfg.get("version_dir", "Agriculture-Vision-2021")
    out_dir = root / seg_cfg["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda" and seg_cfg.get("cudnn_benchmark", True):
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    aug_cfg = seg_cfg.get("augmentation", {})
    train_transform = build_train_transform(aug_cfg)
    if train_transform:
        print("Train augmentations: NIR+RGB, noise/blur, rgb_dropout for NIR reliance")

    train_ds = AgVisionDataset(
        data_root,
        "train",
        version_dir=version_dir,
        tile_size=data_cfg.get("tile_size", 512),
        max_samples=data_cfg.get("max_train_samples"),
        transform=train_transform,
    )
    val_ds = AgVisionDataset(
        data_root,
        "val",
        version_dir=version_dir,
        tile_size=data_cfg.get("tile_size", 512),
        max_samples=data_cfg.get("max_val_samples"),
        transform=None,
    )
    bs = seg_cfg.get("batch_size", 8)
    nw = seg_cfg.get("num_workers", 4)
    loader_kw: dict[str, Any] = dict(
        batch_size=bs,
        collate_fn=collate_segformer_batch,
        pin_memory=device.type == "cuda",
    )
    if nw > 0:
        loader_kw["num_workers"] = nw
        loader_kw["prefetch_factor"] = seg_cfg.get("prefetch_factor", 2)
        if seg_cfg.get("persistent_workers", True):
            loader_kw["persistent_workers"] = True

    train_loader = DataLoader(train_ds, shuffle=True, **loader_kw)
    val_bs = seg_cfg.get("val_batch_size", min(bs, 2))
    val_loader = DataLoader(
        val_ds,
        shuffle=False,
        batch_size=val_bs,
        collate_fn=collate_segformer_batch,
        pin_memory=device.type == "cuda",
        num_workers=0 if nw == 0 else min(2, nw),
    )

    best_path = out_dir / "best_iou.pth"
    last_path = out_dir / "last_epoch.pth"
    if seg_cfg.get("backup_before_train", True):
        _backup_checkpoint(best_path)

    model = Segformer4ChWrapper(
        seg_cfg["model_id"],
        num_labels=seg_cfg.get("num_labels", 2),
    ).to(device)
    expand_segformer_to_4ch(model.model)

    start_epoch = 1
    best_iou = -1.0
    if seg_cfg.get("resume", False) and best_path.is_file():
        ckpt = torch.load(best_path, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state"])
        start_epoch = int(ckpt.get("epoch", 0)) + 1
        best_iou = float(ckpt.get("val_metrics", {}).get("iou_mean", -1.0))
        print(f"Resume from {best_path}, epoch {start_epoch}, best_iou={best_iou:.4f}")

    if seg_cfg.get("gradient_checkpointing", False):
        if hasattr(model.model, "gradient_checkpointing_enable"):
            model.model.gradient_checkpointing_enable()
            print("gradient_checkpointing enabled")
        elif hasattr(model.model, "segformer"):
            model.model.segformer.gradient_checkpointing_enable()
            print("segformer gradient_checkpointing enabled")

    if seg_cfg.get("compile", False) and hasattr(torch, "compile"):
        try:
            model = torch.compile(model)
            print("torch.compile enabled")
        except Exception as e:
            print(f"torch.compile skipped: {e}")

    base_lr = seg_cfg.get("learning_rate", 6e-5)
    opt = torch.optim.AdamW(
        model.parameters(),
        lr=base_lr,
        weight_decay=seg_cfg.get("weight_decay", 0.01),
    )
    epochs = seg_cfg.get("epochs", 40)
    scheduler = None
    if seg_cfg.get("cosine_lr", True):
        t_max = max(1, epochs - start_epoch + 1)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=t_max, eta_min=base_lr * 0.05)
    use_amp = seg_cfg.get("fp16", True) and device.type == "cuda"
    scaler = _amp_scaler(use_amp)
    val_tta = seg_cfg.get("val_tta", False)
    final_tta = seg_cfg.get("final_tta", True)
    accum = max(1, int(seg_cfg.get("gradient_accumulation_steps", 1)))
    patience = int(seg_cfg.get("early_stop_patience", 10))
    stale_epochs = 0
    label_smooth = float(seg_cfg.get("label_smoothing", 0.05))

    print(f"Train tiles: {len(train_ds)}, val tiles: {len(val_ds)}, epochs {start_epoch}-{epochs}")

    for epoch in range(start_epoch, epochs + 1):
        model.train()
        losses = []
        opt.zero_grad(set_to_none=True)
        for step, batch in enumerate(tqdm(train_loader, desc=f"epoch {epoch}/{epochs}")):
            if epoch == start_epoch and step == 0:
                _log_batch_nir_stats(batch)
            x = batch["pixel_values"].to(device, non_blocking=True)
            labels = batch["labels"].to(device, non_blocking=True)
            vm = batch["valid_mask"].to(device, non_blocking=True)
            with _amp_autocast(use_amp):
                out = model(x)
                logits = out.logits
                loss = masked_ce_dice_loss(
                    logits,
                    labels,
                    vm,
                    fg_weight=seg_cfg.get("foreground_weight", 3.0),
                    dice_weight=seg_cfg.get("dice_weight", 0.4),
                    label_smoothing=label_smooth,
                )
                loss = loss / accum
            if scaler is not None:
                scaler.scale(loss).backward()
            else:
                loss.backward()
            if (step + 1) % accum == 0 or (step + 1) == len(train_loader):
                if scaler is not None:
                    scaler.step(opt)
                    scaler.update()
                else:
                    opt.step()
                opt.zero_grad(set_to_none=True)
            losses.append(loss.item() * accum)

        if device.type == "cuda":
            torch.cuda.empty_cache()

        metrics = run_validation(
            model,
            val_loader,
            device,
            threshold=seg_cfg.get("val_threshold", 0.5),
            tta=val_tta,
        )
        lr_now = opt.param_groups[0]["lr"]
        print(
            f"epoch {epoch}: loss={np.mean(losses):.4f} lr={lr_now:.2e} "
            f"val_iou={metrics['iou_mean']:.4f} "
            f"P={metrics['precision_mean']:.4f} R={metrics['recall_mean']:.4f}"
        )
        torch.save(
            {
                "model_state": model.state_dict(),
                "config": config,
                "val_metrics": metrics,
                "epoch": epoch,
                "optimizer": opt.state_dict(),
            },
            last_path,
        )
        if metrics["iou_mean"] > best_iou:
            best_iou = metrics["iou_mean"]
            stale_epochs = 0
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "config": config,
                    "val_metrics": metrics,
                    "epoch": epoch,
                    "optimizer": opt.state_dict(),
                },
                best_path,
            )
        else:
            stale_epochs += 1
            if patience > 0 and stale_epochs >= patience:
                print(f"Early stop: no IoU improvement for {patience} epochs")
                break

        if scheduler is not None:
            scheduler.step()

    # Финальный отчёт
    ckpt = torch.load(best_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state"])
    # финальный val на полном наборе (без лимита max_val_samples)
    full_val_ds = AgVisionDataset(
        data_root,
        "val",
        version_dir=version_dir,
        tile_size=data_cfg.get("tile_size", 512),
        max_samples=None,
    )
    full_val_loader = DataLoader(
        full_val_ds,
        shuffle=False,
        batch_size=val_bs,
        collate_fn=collate_segformer_batch,
        pin_memory=device.type == "cuda",
        num_workers=0 if nw == 0 else min(2, nw),
    )
    final_metrics = run_validation(
        model, full_val_loader, device, tta=final_tta
    )
    report = compare_to_tz_targets(final_metrics)
    report["segmentation"] = final_metrics
    report_path = root / config["metrics"]["report_path"]
    save_metrics_report(report_path, report)
    print(f"Best checkpoint: {best_path}, metrics: {report_path}")
    return best_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/agvision.yaml")
    parser.add_argument("--data-root", default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    train(cfg, data_root=Path(args.data_root) if args.data_root else None)


if __name__ == "__main__":
    main()
