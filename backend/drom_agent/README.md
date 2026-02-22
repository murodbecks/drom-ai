# Drom Agent 🤖

A sketch-to-3D scene reconstruction agent. This module takes a 2D sketch and a set of 3D objects (.glb) and automatically positions, scales, and rotates them to match the sketch using LLM-powered spatial reasoning.

## 📦 Installation

1. **Install dependencies:**
   Ensure you have Python 3.10+ installed.
   ```bash
   pip install -r requirements.txt
   ```

2. **System Dependencies (Linux only):**
   If you are on Linux, you may need EGL for headless rendering:
   ```bash
   sudo apt-get install libgl1-mesa-glx libosmesa6
   ```

3. **Environment Variables:**
   Move `.env.sample` to a `.env` file in your project root with your API keys:
   ```env
   ANTHROPIC_API_KEY=sk-ant-...
   GCLOUD_PROJECT_ID=your-google-project-id
   ```

## 🚀 Usage

You can use the agent via the command line or import it as a Python module.

### CLI Usage

Run the agent directly from the terminal:

```bash
# Using Claude (default)
python -m backend.drom_agent.agent \
  --image backend/drom_agent/assets/03_sample.jpg \
  --objects cat:backend/drom_agent/assets/03_cat.glb \
            table:backend/drom_agent/assets/03_table.glb \
            mouse:backend/drom_agent/assets/03_mouse.glb \
  --output backend/drom_agent/output/my_scene.glb

# Using Gemini
python -m backend.drom_agent.agent \
  --provider gemini \
  --image ... \
  --objects ...
```

### Python API

Import `DromAgent` into your application logic:

```python
from backend.drom_agent import DromAgent

# Initialize the agent
agent = DromAgent(provider="claude", max_iterations=10)

# Run reconstruction
result = agent.run(
    image_path="path/to/sketch.jpg",
    objects={
        "house": "path/to/house.glb",
        "table": "path/to/table.glb"
    },
    output_path="output/final_scene.glb"
)

print(f"Success! Saved to {result['glb_path']}")
```

## 📂 Project Structure

- **`agent.py`**: Main entry point and orchestration logic.
- **`scene_manager.py`**: Handles 3D transformations, rendering, and GLB export.
- **`runners/`**: LLM-specific implementations (Claude, Gemini) that handle prompt engineering and tool execution.
- **`assets/`**: Sample sketches and GLB models for testing.
- **`output/`**: Generated scenes and debug renders.

## 🛠 Features

- **Multi-Provider Support**: Switch easily between Claude (Anthropic) and Gemini (Google).
- **Iterative Feedback**: The agent renders intermediate views, compares them to the sketch, and self-corrects.
- **4-View Diagnostics**: Generates Front, Top, Right, and Sketch-Angle views to ensure accurate placement.
- **Automatic GLB Export**: Produces a single, combined `.glb` file ready for web display.