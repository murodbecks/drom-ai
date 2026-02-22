"""Shared tool definitions and base runner logic."""

from abc import ABC, abstractmethod
from pathlib import Path
import json

from scene_manager import SceneManager


# ── Tool definitions (provider-agnostic) ──────────────────────────────

TOOLS_SCHEMA = [
    {
        "name": "set_position",
        "description": (
            "Set world-space position of an object. "
            "+X=right, +Y=up, +Z=toward camera. "
            "Ground plane is Y=0."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name"},
                "x": {"type": "number", "description": "X position (negative=left, positive=right)"},
                "y": {"type": "number", "description": "Y position (0=ground, positive=up)"},
                "z": {"type": "number", "description": "Z position (negative=far/back, positive=near/front)"},
            },
            "required": ["name", "x", "y", "z"],
        },
    },
    {
        "name": "set_rotation",
        "description": "Set Euler rotation in degrees. Most objects only need Y rotation (turning left/right).",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name"},
                "rx": {"type": "number", "description": "Rotation around X axis (tilt forward/back)"},
                "ry": {"type": "number", "description": "Rotation around Y axis (turn left/right)"},
                "rz": {"type": "number", "description": "Rotation around Z axis (roll)"},
            },
            "required": ["name", "rx", "ry", "rz"],
        },
    },
    {
        "name": "set_scale",
        "description": "Set scale factors. Use uniform scaling (same sx/sy/sz) unless sketch shows distortion.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name"},
                "sx": {"type": "number", "description": "Scale X"},
                "sy": {"type": "number", "description": "Scale Y"},
                "sz": {"type": "number", "description": "Scale Z"},
            },
            "required": ["name", "sx", "sy", "sz"],
        },
    },
    {
        "name": "get_scene_info",
        "description": "Get current transforms and bounding box sizes of all objects.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "render_and_review",
        "description": (
            "Render 4 diagnostic views as 2x2 grid: "
            "Front (check X/Y), Right Side (check Z/Y), "
            "Top Down (check X/Z spacing), Sketch Angle (overall match). "
            "Call after making changes."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "finalize_scene",
        "description": "Export final .glb file. ONLY call when layout matches the reference sketch well.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


def build_system_prompt(objects_info: dict, object_names: list[str]) -> str:
    """Build a detailed system prompt with spatial reasoning guidance."""
    info_str = json.dumps(objects_info, indent=2)
    names_str = ", ".join(object_names)

    return f"""\
You are an expert 3D scene layout assistant. Your task is to position 3D objects to accurately recreate a 2D reference sketch.

## COORDINATE SYSTEM (Right-handed, Y-up)
- **X axis**: Negative = LEFT, Positive = RIGHT
- **Y axis**: 0 = GROUND, Positive = UP (objects sit on Y=0)
- **Z axis**: Negative = FAR/BACK, Positive = NEAR/FRONT (toward camera)

## OBJECTS TO PLACE
Names: {names_str}

Sizes and bounds (in world units):
{info_str}

## SKETCH-TO-3D INTERPRETATION RULES

### Depth (Z-axis) from vertical position in sketch:
- Objects LOWER in the sketch = CLOSER to camera = LARGER Z value
- Objects HIGHER in the sketch = FARTHER from camera = SMALLER Z value
- Example: If a table appears below a house in sketch, table has larger Z than house

### Horizontal position (X-axis):
- Objects on LEFT side of sketch = NEGATIVE X
- Objects on RIGHT side of sketch = POSITIVE X
- Center of sketch ≈ X = 0

### Vertical position (Y-axis):
- Most objects sit on ground: base at Y = 0
- Stacked objects: Y = height of object below
- Flying/floating objects: Y > 0

### Size and scale:
- Objects appearing LARGER in sketch might be closer OR actually bigger
- Use the provided bounding box sizes to estimate appropriate scales
- Prefer uniform scaling (sx = sy = sz) unless sketch shows distortion

### Rotation (usually Y-axis only):
- Objects facing camera: ry = 0
- Objects turned left: ry = positive degrees
- Objects turned right: ry = negative degrees
- Most objects need only Y rotation; rarely need X or Z rotation

## THE 4 DIAGNOSTIC VIEWS

When you call render_and_review, you'll see:

1. **Front View** (top-left): Camera looks at -Z direction
   - Check: Left/right positions (X), heights (Y)
   - Objects should match horizontal arrangement in sketch

2. **Right Side View** (top-right): Camera looks at -X direction
   - Check: Depth ordering (Z), heights (Y)
   - Objects in front of sketch should be at higher Z

3. **Top Down View** (bottom-left): Camera looks at -Y direction
   - Check: Floor plan layout (X and Z)
   - Verify spacing between objects
   - Most useful for depth arrangement

4. **Sketch Angle View** (bottom-right): Similar to reference sketch angle
   - Check: Overall composition match
   - This should look most like the reference

## WORKFLOW

1. **Analyze** the reference sketch:
   - Identify each object's approximate position
   - Note which objects are in front/behind others
   - Note left/right arrangement

2. **Initial placement**: Call set_position for ALL objects with your best estimates
   - Start with rough positions, you'll refine later

3. **Render**: Call render_and_review to see result

4. **Compare systematically**:
   - Front view: Are objects at correct X positions? Correct heights?
   - Top view: Are depth relationships correct? Spacing good?
   - Sketch angle: Does overall composition match?

5. **Adjust**: Fix the largest errors first
   - If object too far left: increase X
   - If object too far back: increase Z
   - If object too small: increase scale

6. **Iterate**: Render again and repeat until satisfied

7. **Finalize**: Call finalize_scene when layout matches well

## COMMON MISTAKES TO AVOID
- Forgetting that lower-in-sketch means higher Z (closer)
- Placing all objects at Z=0 (they'd stack on same depth plane)
- Not checking Top Down view for depth/spacing
- Making too many tiny adjustments instead of fixing big errors first

## RESPONSE FORMAT
- Be CONCISE. Prefer tool calls over explanations.
- Make multiple set_position calls, THEN one render_and_review.
- After seeing render, briefly state what needs adjustment, then fix it.
- Maximum 1-2 sentences of text per response.
"""


def build_initial_user_prompt(object_names: list[str], objects_info: dict) -> str:
    """Build detailed initial user prompt."""
    names_str = ", ".join(object_names)

    # Create a quick reference of object sizes
    size_hints = []
    for name, info in objects_info.items():
        size = info.get("size_xyz", [0, 0, 0])
        size_hints.append(f"  - {name}: {size[0]:.1f}w × {size[1]:.1f}h × {size[2]:.1f}d")
    sizes_str = "\n".join(size_hints)

    return f"""\
**TASK**: Position these objects to match the reference sketch above.

**OBJECTS** (currently all at origin):
{sizes_str}

**INSTRUCTIONS**:
1. Study the reference sketch carefully
2. Estimate where each object should be placed:
   - Which is leftmost/rightmost? (X positions)
   - Which is closest/farthest from camera? (Z positions - remember: lower in sketch = higher Z)
   - What's the approximate spacing between objects?
3. Call set_position for each object with your estimates
4. Call render_and_review to see the result
5. Compare the 4 views with the reference and adjust

**START**: Analyze the sketch, then place all objects with set_position calls."""


def build_review_prompt(iteration: int, max_iterations: int) -> str:
    """Build prompt for after rendering."""
    remaining = max_iterations - iteration
    return f"""\
**4-VIEW RENDER** (iteration {iteration}, {remaining} remaining)

Compare with the reference sketch:
- **Front view**: Check X positions and heights
- **Top view**: Check depth (Z) spacing between objects  
- **Sketch angle**: Check overall composition

What needs adjustment? Make corrections with set_position/set_rotation/set_scale, then render_and_review again.
Or call finalize_scene if the layout matches well."""


def build_nudge_prompt() -> str:
    """Prompt to nudge model when it doesn't use tools."""
    return """\
Please use tool calls to proceed:
- set_position to move objects
- render_and_review to see current state
- finalize_scene when done

Do not explain, just call the tools."""


def execute_tool(
    scene: SceneManager, name: str, args: dict, output_prefix: str
) -> tuple[dict, str | None, bool]:
    """
    Execute a tool call.
    Returns (result_dict, rendered_image_path or None, is_finalized).
    """
    print(f"  ⚙️  {name}({json.dumps(args, default=str)})")
    rendered_path = None
    is_finalized = False

    if name == "set_position":
        result = scene.set_position(args["name"], args["x"], args["y"], args["z"])
    elif name == "set_rotation":
        result = scene.set_rotation(args["name"], args["rx"], args["ry"], args["rz"])
    elif name == "set_scale":
        result = scene.set_scale(args["name"], args["sx"], args["sy"], args["sz"])
    elif name == "get_scene_info":
        result = scene.get_scene_info()
    elif name == "render_and_review":
        path = scene.render_multi_view()
        result = {"status": "rendered", "path": path}
        rendered_path = path
    elif name == "finalize_scene":
        filename = f"{output_prefix}_final.glb"
        path = scene.export_scene(filename)
        result = {"status": "finalized", "path": path}
        is_finalized = True
    else:
        result = {"error": f"Unknown tool: {name}"}

    return result, rendered_path, is_finalized


def read_image_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


def guess_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")


class BaseRunner(ABC):
    """Abstract base for LLM runners."""

    def __init__(
        self,
        image_path: str,
        object_map: dict[str, str],
        assets_dir: str = "assets",
        output_dir: str = "output",
        max_iterations: int = 15,
    ):
        self.image_path = image_path
        self.object_map = object_map
        self.assets_dir = assets_dir
        self.output_dir = output_dir
        self.max_iterations = max_iterations

        # Derive output prefix from image name
        self.output_prefix = Path(image_path).stem

        self.scene = SceneManager(assets_dir=assets_dir, output_dir=output_dir)
        self.objects_info: dict = {}
        self.object_names: list[str] = []

    def load_objects(self) -> None:
        """Load all GLB objects into the scene."""
        for obj_name, filename in self.object_map.items():
            info = self.scene.load_object(obj_name, filename)
            self.objects_info[obj_name] = info
            self.object_names.append(obj_name)
            print(
                f"  ✅  Loaded {obj_name}: "
                f"size={[round(v, 2) for v in info['size_xyz']]}"
            )

    @abstractmethod
    def run(self) -> str:
        """Run the reconstruction loop. Returns path to final GLB."""
        pass

    def cleanup(self) -> None:
        self.scene.cleanup()