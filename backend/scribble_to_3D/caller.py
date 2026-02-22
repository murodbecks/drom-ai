#!/usr/bin/env python3
import shlex
import subprocess
from pathlib import Path
import uuid

# ======================
# CONFIG (set once)
# ======================
INSTANCE = "gpu-playground2"
ZONE = "us-central1-f"

REMOTE_INPUT_DIR = "~/images"          # where images are uploaded on the VM
REMOTE_PROJECT_DIR = "~"           # where inference.py lives
REMOTE_OUTPUT_GLB = "~/output/0/mesh.obj"  # what the VM produces

LOCAL_DOWNLOAD_DIR = Path("./objects")  # where we put the .obj locally

REMOTE_PYTHON = "python3"  # or "python3"
REMOTE_INFERENCE = "inference.py"  # change if needed

# If your pipeline command differs, edit this template:

GCLOUD = "/opt/homebrew/bin/gcloud"  # <-- replace with your `which gcloud` output

# ======================
# IMPLEMENTATION
# ======================

def _run(cmd: list[str]) -> None:
    print(">", " ".join(shlex.quote(c) for c in cmd))
    p = subprocess.run(cmd, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {p.returncode}")


def scribble_to_3d(local_image_path: str) -> Path:
    """
    Uploads the image to the A100 VM, runs inference, downloads the resulting GLB.
    Returns the local path to the GLB.
    """
    local_img = Path(local_image_path).expanduser().resolve()
    if not local_img.exists():
        raise FileNotFoundError(f"Input image not found: {local_img}")

    LOCAL_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Give the uploaded file a unique name to avoid caching/collisions on the VM
    remote_name = f"{local_img.stem}_{uuid.uuid4().hex[:8]}{local_img.suffix}"
    remote_input_path = f"{REMOTE_INPUT_DIR.rstrip('/')}/{remote_name}"

    # 1) Upload
    _run([
        "gcloud", "compute", "scp",
        str(local_img),
        f"{INSTANCE}:{REMOTE_INPUT_DIR}/{remote_name}",
        "--zone", ZONE,
    ])

    # 2) Process

    remote_cmd = (
    'cd "$HOME" && '
    'source "$HOME/ComfyUI/.venv/bin/activate" && '
    'python "$HOME/inference.py" '
    '--workflow "$HOME/Drom_scribble_to_2D.json" '
    f'--input "$HOME/images/{remote_name}" '
    '--image-node-id 15 '
    '--image-input-key image '
    '--out "$HOME/result.png"'
)

    _run([
        "gcloud", "compute", "ssh",
        INSTANCE,
        "--zone", ZONE,
        "--command", remote_cmd,
    ])

    # 3) Download
    # Download into download dir, then rename to match the input stem
    _run([
        "gcloud", "compute", "scp",
        f"{INSTANCE}:{REMOTE_OUTPUT_GLB}",
        str(LOCAL_DOWNLOAD_DIR) + "/",
        "--zone", ZONE,
    ])

    downloaded = LOCAL_DOWNLOAD_DIR / Path(REMOTE_OUTPUT_GLB).name  # usually result.obj
    final_glb = LOCAL_DOWNLOAD_DIR / f"{local_img.stem}.obj"
    if final_glb.exists():
        final_glb.unlink()
    downloaded.rename(final_glb)

    return final_glb


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python scribble_to_3d.py /path/to/scribble.png")
        raise SystemExit(2)

    out = scribble_to_3d(sys.argv[1])
    print(str(out))