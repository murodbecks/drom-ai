# Scribble to 3D

Scribble/image to 3D mesh pipeline built around:
- **ComfyUI** (2D image generation from scribble/workflow)
- **TripoSR** (single-image 3D reconstruction)
- Optional **GCP VM automation** (`caller.py`) for remote execution

## Repository layout

- `caller.py`: Upload image to a GCP VM, run remote inference, download final `.obj`.
- `archive/inference.py`: Run a ComfyUI workflow, download generated image, then call `TripoSR/run.py`.
- `archive/Drom_scribble_to_2D_API.json`: ComfyUI workflow JSON used by `archive/inference.py`.
- `TripoSR/`: Upstream TripoSR project (model code + CLI + gradio app).
- `assets/`: Example input images.
- `objects/`: Downloaded/generated meshes from `caller.py`.
- `notes/cpu_fallback_solution.txt`: MPS fallback env var tip for macOS.

## Prerequisites

### 1) Python environment

Use the existing virtual environment in this repo:

```bash
source Env/bin/activate
```

Or create your own and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools
git clone https://github.com/VAST-AI-Research/TripoSR.git
pip install -r TripoSR/requirements.txt
pip install requests
```

Install PyTorch for your platform first if needed:
- https://pytorch.org/get-started/locally/

### 2) Optional macOS fallback

If running on Apple Silicon and you hit MPS op issues:

```bash
export PYTORCH_ENABLE_MPS_FALLBACK=1
```

(From `notes/cpu_fallback_solution.txt`.)

### 3) For remote VM flow (`caller.py`)

- `gcloud` CLI installed and authenticated.
- Access to the configured instance and zone.
- Remote machine must have all of the following:
  1. ComfyUI venv at `~/ComfyUI/.venv`
  2. `inference.py` at `~/inference.py`
  3. Workflow file at `~/Drom_scribble_to_2D.json`
  4. TripoSR code available at `~/TripoSR`

## Usage

### A) Run TripoSR directly (local image -> 3D)

```bash
python TripoSR/run.py assets/chair.webp --output-dir output/
```

Output mesh is saved under `output/0/mesh.obj` by default.

Useful options:

```bash
python TripoSR/run.py --help
```

Common flags:
- `--device cpu` to force CPU
- `--model-save-format glb` for GLB output
- `--bake-texture` to bake texture atlas
- `--render` to also export a turntable video

### B) Run ComfyUI workflow + TripoSR locally (`archive/inference.py`)

Start ComfyUI (default expected URL is `http://localhost:8188`), then run:

```bash
python archive/inference.py \
  --workflow archive/Drom_scribble_to_2D_API.json \
  --input assets/A.png \
  --image-node-id 15 \
  --image-input-key image \
  --out output/result.png
```

What this script does:
1. Uploads the input image to ComfyUI.
2. Queues the workflow and waits for completion.
3. Downloads output image from node `27`.
4. Runs `python TripoSR/run.py <downloaded_image> --output-dir output/`.

Final mesh is written to `output/0/mesh.obj`.

Important workflow assumptions in current code:
- Prompt node id: `6`
- Input image node id: `15`
- Sampler seed node id: `3`
- Saved output image node id: `27`

If your workflow uses different node IDs, update `archive/inference.py`.

### C) Run full remote pipeline via GCP (`caller.py`)

Update constants in `caller.py` first:
- `INSTANCE`, `ZONE`
- `REMOTE_INPUT_DIR`
- `REMOTE_OUTPUT_GLB` (currently points to `~/output/0/mesh.obj`)

Then run:

```bash
python caller.py "assets/happy cat with short arms standing.jpg"
```

Flow:
1. Uploads your local image to the VM with `gcloud compute scp`.
2. SSHes into VM and runs remote `inference.py`.
3. Downloads remote mesh into local `objects/`.
4. Renames output to match input filename stem.

Example result path:
- `objects/happy cat with short arms standing.obj`

### D) Receive latest frontend box image (`upload_server.py`)

Start a lightweight upload API that saves the frontend's latest generated box PNG into `objects/`:

```bash
source Env/bin/activate
python -m uvicorn upload_server:app --host 0.0.0.0 --port 8000 --reload
```

Endpoint:
- `POST /upload-latest-box` (multipart form-data)
- required field: `image`
- optional fields: `label`, `globalPrompt`, `box`

## Notes

- `caller.py` prints usage text mentioning `scribble_to_3d.py`; actual filename here is `caller.py`.
- `TripoSR/` is maintained as its own nested git repo.
