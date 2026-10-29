"""Dedicated AI Handwriting Inference & Job Queue Service (CPU default, CUDA GPU auto-detect, remote GPU bridge)."""
from __future__ import annotations

import base64
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .handwriting_ai import (
    compare_handwriting_style,
    extract_style_profile,
    get_generator,
    synthesize_korean_sentence,
)
from .render import png_bytes

inference_app = FastAPI(title="InkLab AI Inference Service", version="2.0.0")

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.RLock()
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="inklab-job")


def detect_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return f"cuda:{torch.cuda.get_device_name(0)}"
    except ImportError:
        pass
    return "cpu"


class InferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    size: int = Field(default=36, ge=8, le=128)
    color: str = Field(default="#243d78", pattern=r"^#[0-9a-fA-F]{6}$")
    seed: int = Field(default=7, ge=0, le=2147483647)
    profile: dict = Field(default_factory=lambda: {"id": "default", "glyphs": {}, "strokes": {}})


def create_job(kind: str, fn: Callable[[], dict[str, Any]], sync_if_fast: bool = True) -> dict[str, Any]:
    """Create and track a Job ID for long-running AI generation, PDF analysis, or rendering."""
    job_id = uuid.uuid4().hex
    record = {
        "job_id": job_id,
        "kind": kind,
        "status": "running",
        "created_at": round(time.time(), 3),
        "result": None,
        "error": None,
    }
    with _JOBS_LOCK:
        if len(_JOBS) > 500:
            oldest = sorted(_JOBS.keys(), key=lambda k: _JOBS[k]["created_at"])[:100]
            for k in oldest:
                _JOBS.pop(k, None)
        _JOBS[job_id] = record

    def _runner():
        try:
            res = fn()
            with _JOBS_LOCK:
                record["status"] = "completed"
                record["completed_at"] = round(time.time(), 3)
                record["result"] = res
        except Exception as exc:
            with _JOBS_LOCK:
                record["status"] = "failed"
                record["completed_at"] = round(time.time(), 3)
                record["error"] = str(exc)

    if sync_if_fast:
        _runner()
    else:
        _EXECUTOR.submit(_runner)
    return get_job(job_id)


def get_job(job_id: str) -> dict[str, Any]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise ValueError(f"작업 ID({job_id})를 찾을 수 없습니다.")
        return dict(job)


def run_handwriting_inference(req: InferenceRequest) -> dict[str, Any]:
    remote_url = os.environ.get("INKLAB_INFERENCE_URL", "").rstrip("/")
    if remote_url:
        try:
            import httpx
            resp = httpx.post(f"{remote_url}/generate", json=req.model_dump(), timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

    gen = get_generator()
    style = extract_style_profile(req.profile)
    dots = gen.generate_dots(req.text, seed=req.seed, seed_seq=list(style["_seed_tuple"]) or None)
    synth = synthesize_korean_sentence(req.text, req.size, req.color, req.profile, seed=req.seed)
    comp = compare_handwriting_style(req.profile, req.text)
    encoded_png = base64.b64encode(png_bytes(synth["image"])).decode()
    return {
        "device": detect_device(),
        "text": req.text,
        "num_points": len(dots),
        "dots": dots[:300],
        "direct_glyphs": synth["direct_glyphs"],
        "ai_generated_glyphs": synth["ai_generated_glyphs"],
        "style": synth["style"],
        "similarity_score": comp["similarity_score"],
        "png_base64": encoded_png,
    }


@inference_app.get("/health")
def health():
    gen = get_generator()
    return {
        "status": "ok",
        "service": "inklab-inference",
        "device": detect_device(),
        "model_loaded": bool(gen.w),
        "remote_gpu_url": os.environ.get("INKLAB_INFERENCE_URL", ""),
        "active_jobs": len(_JOBS),
    }


@inference_app.post("/generate")
def generate(body: InferenceRequest):
    return run_handwriting_inference(body)


@inference_app.post("/jobs/generate")
def submit_generate_job(body: InferenceRequest):
    return create_job("generate_handwriting", lambda: run_handwriting_inference(body), sync_if_fast=True)


@inference_app.get("/jobs/{job_id}")
def job_status(job_id: str):
    try:
        return get_job(job_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
