#!/usr/bin/env python3
"""
Unified entry point for sketch-to-3D reconstruction.

Usage:
    # Using Claude (default)
    python main.py --image assets/02_sample.jpg \
        --objects house:02_house.glb bench:02_long-table.glb table:02_circle-table.glb

    # Using Gemini
    python main.py --provider gemini --image assets/02_sample.jpg \
        --objects house:02_house.glb bench:02_long-table.glb table:02_circle-table.glb

    # Specify model
    python main.py --provider claude --model claude-3-5-haiku-20241022 ...
"""

import argparse
from dotenv import load_dotenv

load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reconstruct 3D scene from sketch"
    )
    parser.add_argument(
        "--provider",
        choices=["claude", "gemini"],
        default="claude",
        help="LLM provider (default: claude)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (uses provider default if not specified)",
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Path to reference sketch",
    )
    parser.add_argument(
        "--objects",
        nargs="+",
        required=True,
        help="name:filename.glb pairs",
    )
    parser.add_argument("--assets-dir", default="assets")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--max-iterations", type=int, default=15)
    return parser.parse_args()


def main():
    args = parse_args()

    # Parse object map
    object_map: dict[str, str] = {}
    for item in args.objects:
        if ":" not in item:
            print(f"  ❌  Invalid format: '{item}'. Use name:file.glb")
            return
        name, filename = item.split(":", 1)
        object_map[name] = filename

    # Select runner
    if args.provider == "claude":
        from runners import ClaudeRunner

        model = args.model or "claude-opus-4-5-20251101"
        runner = ClaudeRunner(
            image_path=args.image,
            object_map=object_map,
            assets_dir=args.assets_dir,
            output_dir=args.output_dir,
            max_iterations=args.max_iterations,
            model=model,
        )
    else:
        from runners import GeminiRunner

        model = args.model or "gemini-2.5-pro"
        runner = GeminiRunner(
            image_path=args.image,
            object_map=object_map,
            assets_dir=args.assets_dir,
            output_dir=args.output_dir,
            max_iterations=args.max_iterations,
            model=model,
        )

    runner.run()


if __name__ == "__main__":
    main()