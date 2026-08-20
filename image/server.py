"""CPU image worker with an Automatic1111-compatible txt2img endpoint."""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from aiohttp import web

logger = logging.getLogger("arkann.image")

DEFAULT_MODEL = "stabilityai/sd-turbo"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7860
MAX_EDGE = 768
DEFAULT_EDGE = 512

_pipe = None
_pipe_lock = threading.Lock()
_ready = False
_error: str | None = None
_model_id = DEFAULT_MODEL
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sd")


def round_edge(value: int, *, default: int = DEFAULT_EDGE, maximum: int = MAX_EDGE) -> int:
    size = int(value or default)
    size = max(64, min(size, maximum))
    return max(64, (size // 8) * 8)


def _load_pipeline(model_id: str) -> None:
    global _pipe, _ready, _error, _model_id
    try:
        import torch
        from diffusers import AutoPipelineForText2Image

        threads = max(1, min(6, (os.cpu_count() or 4) // 2 or 1))
        torch.set_num_threads(threads)
        logger.info("Loading %s on CPU (%s threads)…", model_id, threads)
        pipe = AutoPipelineForText2Image.from_pretrained(model_id, torch_dtype=torch.float32)
        pipe.to("cpu")
        if hasattr(pipe, "enable_attention_slicing"):
            pipe.enable_attention_slicing()
        pipe.set_progress_bar_config(disable=True)
        with _pipe_lock:
            _pipe = pipe
            _model_id = model_id
            _ready = True
            _error = None
        logger.info("Image model ready: %s", model_id)
    except Exception as exc:
        with _pipe_lock:
            _error = str(exc)
            _ready = False
        logger.exception("Failed to load image model %s", model_id)


def _infer(payload: dict[str, Any]) -> bytes:
    import torch

    prompt = str(payload.get("prompt") or "").strip()
    negative = str(payload.get("negative_prompt") or "")
    width = round_edge(int(payload.get("width") or DEFAULT_EDGE))
    height = round_edge(int(payload.get("height") or DEFAULT_EDGE))
    turbo = "turbo" in _model_id.casefold()
    if turbo:
        steps = max(1, min(int(payload.get("steps") or 2), 4))
        guidance = 0.0
    else:
        steps = max(1, min(int(payload.get("steps") or 4), 12))
        guidance = float(payload.get("cfg_scale") or 7)
    seed = payload.get("seed")
    generator = None
    if seed not in (None, "", -1):
        generator = torch.Generator(device="cpu").manual_seed(int(seed))

    with _pipe_lock:
        pipe = _pipe
        if pipe is None:
            raise RuntimeError(_error or "Model is not loaded.")
        result = pipe(
            prompt=prompt,
            negative_prompt=negative or None,
            num_inference_steps=steps,
            guidance_scale=guidance,
            width=width,
            height=height,
            generator=generator,
        )
    image = result.images[0]
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def handle_health(_request: web.Request) -> web.Response:
    if _ready:
        return web.json_response({"ok": True, "model": _model_id})
    status = 503
    return web.json_response({"ok": False, "error": _error or "loading"}, status=status)


async def handle_txt2img(request: web.Request) -> web.Response:
    if not _ready:
        return web.json_response({"error": _error or "Model is still loading."}, status=503)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict) or not str(payload.get("prompt") or "").strip():
        return web.json_response({"error": "Missing prompt."}, status=400)
    loop = asyncio.get_running_loop()
    try:
        png = await loop.run_in_executor(_executor, _infer, payload)
    except Exception as exc:
        logger.exception("Image inference failed")
        return web.json_response({"error": str(exc)}, status=500)
    encoded = base64.b64encode(png).decode("ascii")
    return web.json_response({"images": [encoded]})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/sdapi/v1/txt2img", handle_txt2img)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Arkann local image server")
    parser.add_argument("--host", default=os.environ.get("ARKANN_IMAGE_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARKANN_IMAGE_PORT", DEFAULT_PORT)))
    parser.add_argument("--model", default=os.environ.get("ARKANN_IMAGE_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()
    threading.Thread(target=_load_pipeline, args=(args.model,), name="sd-load", daemon=True).start()
    web.run_app(create_app(), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
