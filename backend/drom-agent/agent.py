"""Main DromAgent class - single entry point for sketch-to-3D reconstruction."""

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

# Package root directory
PACKAGE_DIR = Path(__file__).parent.resolve()
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "output"


class DromAgent:
    """
    Sketch-to-3D scene reconstruction agent.

    Args:
        provider: LLM provider ("claude" or "gemini")
        model: Model name (uses provider default if None)
        max_iterations: Maximum optimization iterations

    Example:
        agent = DromAgent(provider="claude")
        result = agent.run(
            image_path="sketch.jpg",
            objects={"house": "house.glb", "table": "table.glb"},
            output_path="scene.glb",
        )
        print(result)  # {"glb_path": "...", "preview_path": "...", "iterations": 5}
    """

    def __init__(
        self,
        provider: Literal["claude", "gemini"] = "claude",
        model: str | None = None,
        max_iterations: int = 15,
    ):
        self.provider = provider
        self.model = model
        self.max_iterations = max_iterations

        # Validate provider
        if provider not in ("claude", "gemini"):
            raise ValueError(f"Invalid provider: {provider}. Use 'claude' or 'gemini'.")

        # Set default models
        if self.model is None:
            self.model = (
                "claude-sonnet-4-20250514"
                if provider == "claude"
                else "gemini-2.5-flash"
            )

    def run(
        self,
        image_path: str | Path,
        objects: dict[str, str | Path],
        output_path: str | Path | None = None,
    ) -> dict:
        """
        Run scene reconstruction.

        Args:
            image_path: Path to reference sketch image
            objects: Dict mapping object names to GLB file paths
                     e.g., {"house": "assets/house.glb", "table": "assets/table.glb"}
            output_path: Path for output GLB file. If None, uses default location.
                        If directory, saves as {image_stem}_final.glb in that dir.
                        If file path, saves to that exact path.

        Returns:
            dict with keys:
                - glb_path: Path to exported GLB file
                - preview_path: Path to final multi-view render
                - iterations: Number of iterations used
                - status: "success" or "max_iterations_reached"
        """
        # Resolve image path
        image_path = Path(image_path).resolve()
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Resolve object paths
        resolved_objects: dict[str, Path] = {}
        for name, glb_path in objects.items():
            resolved = Path(glb_path).resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"GLB not found for '{name}': {resolved}")
            resolved_objects[name] = resolved

        # Determine output path
        image_stem = image_path.stem
        if output_path is None:
            # Default: package output directory
            output_dir = DEFAULT_OUTPUT_DIR
            output_dir.mkdir(parents=True, exist_ok=True)
            final_glb_path = output_dir / f"{image_stem}_final.glb"
        else:
            output_path = Path(output_path).resolve()
            if output_path.suffix.lower() == ".glb":
                # It's a file path
                final_glb_path = output_path
                output_dir = output_path.parent
            else:
                # It's a directory
                output_dir = output_path
                final_glb_path = output_dir / f"{image_stem}_final.glb"
            output_dir.mkdir(parents=True, exist_ok=True)

        # Create runner
        runner = self._create_runner(
            image_path=image_path,
            objects=resolved_objects,
            output_dir=output_dir,
            output_stem=image_stem,
        )

        # Run reconstruction
        result = runner.run()

        return result

    def _create_runner(
        self,
        image_path: Path,
        objects: dict[str, Path],
        output_dir: Path,
        output_stem: str,
    ):
        """Create the appropriate runner based on provider."""
        if self.provider == "claude":
            from .runners.claude import ClaudeRunner

            return ClaudeRunner(
                image_path=image_path,
                objects=objects,
                output_dir=output_dir,
                output_stem=output_stem,
                max_iterations=self.max_iterations,
                model=self.model,
            )
        else:
            from .runners.gemini import GeminiRunner

            return GeminiRunner(
                image_path=image_path,
                objects=objects,
                output_dir=output_dir,
                output_stem=output_stem,
                max_iterations=self.max_iterations,
                model=self.model,
            )


# CLI entry point
def main():
    """CLI entry point for direct script execution."""
    import argparse

    parser = argparse.ArgumentParser(description="Drom Agent - Sketch to 3D")
    parser.add_argument("--image", "-i", required=True, help="Reference sketch path")
    parser.add_argument(
        "--objects",
        "-o",
        nargs="+",
        required=True,
        help="name:path.glb pairs",
    )
    parser.add_argument("--output", "-out", help="Output GLB path")
    parser.add_argument(
        "--provider",
        "-p",
        choices=["claude", "gemini"],
        default="claude",
    )
    parser.add_argument("--model", "-m", help="Model name")
    parser.add_argument("--max-iterations", type=int, default=15)

    args = parser.parse_args()

    # Parse objects
    objects = {}
    for item in args.objects:
        if ":" not in item:
            print(f"❌ Invalid format: '{item}'. Use name:path.glb")
            return 1
        name, path = item.split(":", 1)
        objects[name] = path

    # Run agent
    agent = DromAgent(
        provider=args.provider,
        model=args.model,
        max_iterations=args.max_iterations,
    )

    try:
        result = agent.run(
            image_path=args.image,
            objects=objects,
            output_path=args.output,
        )
        print(f"\n✅ Success!")
        print(f"   GLB: {result['glb_path']}")
        print(f"   Preview: {result['preview_path']}")
        print(f"   Iterations: {result['iterations']}")
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())