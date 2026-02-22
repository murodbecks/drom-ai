    #!/usr/bin/env python3
import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Tuple
import subprocess


import requests


def upload_image(comfy_url: str, image_path: Path) -> str:
    with image_path.open("rb") as f:
        r = requests.post(
            f"{comfy_url}/upload/image",
            files={"image": (image_path.name, f, "image/png")},
            data={"type": "input"},
            timeout=300,
        )
    r.raise_for_status()
    return r.json()["name"]


def queue_prompt(comfy_url: str, workflow: Dict[str, Any]) -> str:
    r = requests.post(f"{comfy_url}/prompt", json={"prompt": workflow}, timeout=300)
    r.raise_for_status()
    return r.json()["prompt_id"]


def wait_done(comfy_url: str, prompt_id: str, timeout_s: int = 900):
    import time, requests

    t0 = time.time()
    while True:
        r = requests.get(f"{comfy_url}/history/{prompt_id}", timeout=300)
        r.raise_for_status()
        hist = r.json()
        if prompt_id not in hist:
            time.sleep(0.5)
            continue

        entry = hist[prompt_id]
        status = entry.get("status", {}) or {}
        outputs = entry.get("outputs", {}) or {}

        # ComfyUI typically sets these when finished
        completed = bool(status.get("completed", False))
        status_str = status.get("status_str")  # often "success" / "error" / "running"

        # SUCCESS: completed + has outputs (usually with images)
        if completed and status_str == "success":
            return entry

        # ERROR: completed + error
        if completed and status_str == "error":
            # include messages if present
            raise RuntimeError(f"ComfyUI error. status={status}. outputs_keys={list(outputs.keys())}")

        # Some builds may not set status_str reliably: fallback if outputs becomes non-empty
        if outputs:
            return entry

        if time.time() - t0 > timeout_s:
            raise TimeoutError(f"Timed out waiting for {prompt_id}. status={status}")

        time.sleep(0.5)


def pick_image_from_node(history_entry, node_id: str):
    outputs = history_entry.get("outputs") or {}
    if node_id not in outputs:
        raise KeyError(f"Node {node_id} not found in outputs. Available: {list(outputs.keys())}")
    out = outputs[node_id]
    imgs = out.get("images") or []
    if not imgs:
        raise RuntimeError(f"No images under outputs[{node_id}]. Keys: {list(out.keys())}")
    img0 = imgs[0]
    return img0["filename"], img0.get("subfolder",""), img0.get("type","output")


def download_image(comfy_url: str, filename: str, subfolder: str, ftype: str, out_path: Path) -> None:
    r = requests.get(
        f"{comfy_url}/view",
        params={"filename": filename, "subfolder": subfolder, "type": ftype},
        timeout=300,
    )
    r.raise_for_status()
    out_path.write_bytes(r.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy-url", default="http://localhost:8188")
    ap.add_argument("--workflow", required=True, type=Path)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", default="out.png", type=Path)

    # You MUST set these to match your workflow:
    ap.add_argument("--image-node-id", required=True, help="Node id that receives the image filename (e.g. LoadImage node id)")
    ap.add_argument("--image-input-key", default="image", help="Usually 'image'")

    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    comfy_url = args.comfy_url.rstrip("/")
    workflow = json.loads(args.workflow.read_text(encoding="utf-8"))

    uploaded_name = upload_image(comfy_url, args.input)

    workflow["6"]["inputs"]["text"] = args.input.name

    # 1) upload image -> uploaded_name (string)
    workflow["15"]["inputs"]["image"] = uploaded_name

    # 2) bust cache
    workflow["3"]["inputs"]["seed"] = int(time.time() * 1000)

    # Patch workflow: workflow[node_id]["inputs"][key] = uploaded filename
    node_id = str(args.image_node_id)
    if node_id not in workflow:
        raise KeyError(f"Node id {node_id} not found in workflow JSON keys: {list(workflow.keys())[:10]}...")
    workflow[node_id]["inputs"][args.image_input_key] = uploaded_name

    prompt_id = queue_prompt(comfy_url, workflow)
    hist = wait_done(comfy_url, prompt_id, timeout_s=args.timeout)

    
    filename, subfolder, ftype = pick_image_from_node(hist,"27")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    download_image(comfy_url, filename, subfolder, ftype, args.out)

    print("prompt_id:", prompt_id)
    print("saved:", args.out)
    print("OUTPUT NODE IDS:", list((hist.get("outputs") or {}).keys()))

    subprocess.run(
    ["python", "TripoSR/run.py", str(args.out), "--output-dir", "output/"],
    check=True,
    )
    print("3D output saved to: output/")




if __name__ == "__main__":
    main()