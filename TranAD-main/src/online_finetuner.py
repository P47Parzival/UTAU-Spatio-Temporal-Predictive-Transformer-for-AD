import asyncio
import logging
import sqlite3
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger("online_finetuner")

FT_LR            = float(__import__("os").getenv("FT_LR",            "1e-5"))
FT_EPOCHS        = int(  __import__("os").getenv("FT_EPOCHS",        "3"))
FT_MIN_WINDOWS   = int(  __import__("os").getenv("FT_MIN_WINDOWS",   "1"))
FT_MARGIN_CONF   = float(__import__("os").getenv("FT_MARGIN_CONF",   "0.30"))
FT_MAX_GRAD_NORM = float(__import__("os").getenv("FT_MAX_GRAD_NORM", "1.0"))


def _load_feedback_windows(db_path, n_window, n_feats, limit=200):
    """
    Pull raw_window blobs from operator_feedback.
    Column: was_anomaly INTEGER (1=confirmed, 0=false_positive)
    Column: raw_window  BLOB (float32 bytes)
    """
    windows, labels = [], []
    try:
        con  = sqlite3.connect(db_path, timeout=5)
        rows = con.execute(
            "SELECT raw_window, was_anomaly "
            "FROM operator_feedback "
            "WHERE raw_window IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        con.close()
    except Exception as exc:
        logger.warning("[FINETUNE] feedback DB read failed: %s", exc)
        return windows, labels

    for blob, was_anomaly in rows:
        try:
            flat   = np.frombuffer(blob, dtype=np.float32)
            n_vals = len(flat)
            if n_vals == 0:
                continue
            if n_vals % n_feats != 0:
                logger.debug(
                    "[FINETUNE] Skipping blob: %d floats not divisible by n_feats=%d",
                    n_vals, n_feats,
                )
                continue
            actual_frames = n_vals // n_feats
            arr = flat.reshape(actual_frames, n_feats)
            if actual_frames < n_window:
                pad = np.zeros((n_window - actual_frames, n_feats), dtype=np.float32)
                arr = np.vstack([pad, arr])
                logger.debug("[FINETUNE] Padded blob %d->%d frames", actual_frames, n_window)
            elif actual_frames > n_window:
                arr = arr[-n_window:]
            label = "confirmed" if int(was_anomaly) == 1 else "false_positive"
            windows.append(arr.astype(np.float32))
            labels.append(label)
        except Exception as exc:
            logger.debug("[FINETUNE] Skipping malformed blob: %s", exc)
            continue

    logger.info(
        "[FINETUNE] Loaded %d usable windows — confirmed=%d  false_positive=%d",
        len(windows), labels.count("confirmed"), labels.count("false_positive"),
    )
    return windows, labels


def _one_finetune_pass(model, optimizer, windows, labels, device):
    mse = nn.MSELoss(reduction="mean")
    fp_losses, conf_losses = [], []
    model.train()
    for arr, label in zip(windows, labels):
        # Shape: (n_window, n_feats) -> (n_window, 1, n_feats) for TranAD
        x = torch.tensor(arr, dtype=torch.float64, device=device).unsqueeze(1)
        optimizer.zero_grad()
        try:
            _, x2, _ = model(x)
        except Exception as exc:
            logger.warning("[FINETUNE] Forward pass failed: %s", exc)
            continue
        target     = x[-1].unsqueeze(0)
        recon_loss = mse(x2.double(), target.double())
        if label == "false_positive":
            loss = recon_loss
            fp_losses.append(recon_loss.item())
        else:
            margin = recon_loss.detach() * (1.0 + FT_MARGIN_CONF)
            loss   = torch.clamp(margin - recon_loss, min=0.0)
            conf_losses.append(recon_loss.item())
        if loss.requires_grad and loss.item() > 0:
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), FT_MAX_GRAD_NORM)
            optimizer.step()
    model.eval()
    return {
        "fp_count":       len(fp_losses),
        "conf_count":     len(conf_losses),
        "fp_loss_mean":   float(np.mean(fp_losses))   if fp_losses   else None,
        "conf_loss_mean": float(np.mean(conf_losses)) if conf_losses else None,
    }


def _save_checkpoint(model, checkpoint_dir, version):
    """
    Save using same key schema as your training script: model_state_dict
    Always backs up existing checkpoint to model.ckpt.bak first.
    """
    import shutil
    path     = Path(checkpoint_dir) / "model.ckpt"
    bak_path = Path(checkpoint_dir) / "model.ckpt.bak"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        shutil.copy2(path, bak_path)
        logger.info("[FINETUNE] Backed up existing checkpoint -> %s", bak_path)

    params = list(model.parameters())
    if not params:
        logger.error("[FINETUNE] Model has no parameters — aborting save!")
        return

    torch.save(
        {
            "model_state_dict": model.state_dict(),  # matches training script key
            "epoch":            -1,                  # sentinel: fine-tuned not trained
            "accuracy_list":    [],
            "version":          version,
            "saved_at":         time.time(),
        },
        path,
    )
    logger.info("[FINETUNE] Checkpoint saved -> %s  (version=%s)", path, version)


async def run_finetune(model, optimizer, db_path, checkpoint_dir, device,
                       model_version_ref, retrain_state, model_lock):
    """
    Async entry-point called by server.py _finetune_async_wrapper().
    Runs in background via asyncio.to_thread — inference stream stays unblocked.
    """
    import os
    logger.info("[FINETUNE] db_path=%s  exists=%s  cwd=%s",
                db_path, os.path.exists(db_path), os.getcwd())

    n_window = getattr(model, "n_window", 100)
    n_feats  = getattr(model, "n_feats",   38)
    logger.info("[FINETUNE] Using n_window=%d  n_feats=%d", n_window, n_feats)

    windows, labels = await asyncio.to_thread(
        _load_feedback_windows, db_path, n_window, n_feats
    )

    if len(windows) < FT_MIN_WINDOWS:
        logger.info(
            "[FINETUNE] Skipped: insufficient_windows (windows=%d, need=%d)",
            len(windows), FT_MIN_WINDOWS,
        )
        retrain_state["recommended"] = False
        return {"skipped": True, "reason": "insufficient_windows",
                "windows": len(windows), "need": FT_MIN_WINDOWS}

    epoch_stats = []
    async with model_lock:
        for epoch in range(FT_EPOCHS):
            stats = await asyncio.to_thread(
                _one_finetune_pass, model, optimizer, windows, labels, device
            )
            epoch_stats.append(stats)
            logger.info(
                "[FINETUNE] Epoch %d/%d  fp=%s  conf=%s",
                epoch + 1, FT_EPOCHS, stats.get("fp_count"), stats.get("conf_count"),
            )

        old_ver = model_version_ref.get("version", "v0")
        try:
            num = int(old_ver.lstrip("v")) + 1
        except ValueError:
            num = 1
        new_ver = f"v{num}"
        model_version_ref["version"] = new_ver

        await asyncio.to_thread(_save_checkpoint, model, checkpoint_dir, new_ver)

    retrain_state["recommended"]     = False
    retrain_state["last_applied_ts"] = time.time()

    result = {"skipped": False, "windows_used": len(windows),
              "epochs": FT_EPOCHS, "new_version": new_ver, "epoch_stats": epoch_stats}
    logger.info("[FINETUNE] Complete: %s", result)
    return result