"""Claude-based runner using Anthropic API."""

import os
import base64
from pathlib import Path

import anthropic

from .base import (
    BaseRunner,
    TOOLS_SCHEMA,
    build_system_prompt,
    build_initial_user_prompt,
    build_review_prompt,
    build_nudge_prompt,
    execute_tool,
    read_image_bytes,
    guess_mime,
)


def _build_claude_tools() -> list[dict]:
    """Convert generic tool schema to Claude format."""
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["parameters"],
        }
        for tool in TOOLS_SCHEMA
    ]


def _make_image_block(data: bytes, mime_type: str) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": base64.standard_b64encode(data).decode("utf-8"),
        },
    }


class ClaudeRunner(BaseRunner):
    """Claude-powered scene reconstruction."""

    def __init__(
        self,
        image_path: Path,
        objects: dict[str, Path],
        output_dir: Path,
        output_stem: str,
        max_iterations: int = 15,
        model: str = "claude-sonnet-4-20250514",
    ):
        super().__init__(
            image_path, objects, output_dir, output_stem, max_iterations
        )
        self.model = model
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )

    def run(self) -> dict:
        print(f"  🤖  Provider: Claude ({self.model})")
        print(f"  📷  Reference: {self.image_path}")
        print(f"  📦  Objects: {list(self.objects.keys())}\n")

        self.load_objects()

        # Render initial state
        print("\n  📸  Rendering initial state...")
        initial_path = Path(self.scene.render_multi_view())
        initial_bytes = read_image_bytes(initial_path)

        system_prompt = build_system_prompt(self.objects_info, self.object_names)
        ref_bytes = read_image_bytes(self.image_path)
        ref_mime = guess_mime(self.image_path)

        initial_user_prompt = build_initial_user_prompt(
            self.object_names, self.objects_info
        )

        # Build initial messages
        messages: list[dict] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "**REFERENCE SKETCH** (target layout):"},
                    _make_image_block(ref_bytes, ref_mime),
                    {"type": "text", "text": "**CURRENT STATE** (all objects at origin):"},
                    _make_image_block(initial_bytes, "image/png"),
                    {"type": "text", "text": initial_user_prompt},
                ],
            }
        ]

        tools = _build_claude_tools()
        finalized = False
        final_glb_path = ""
        final_preview_path = ""
        iteration = 0
        status = "max_iterations_reached"

        while iteration < self.max_iterations:
            iteration += 1
            print(f"\n{'='*50}")
            print(f"  Iteration {iteration}/{self.max_iterations}")
            print(f"{'='*50}")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

            # Extract tool uses and text
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            # Print text (truncated)
            if text_blocks:
                combined = " ".join(b.text.strip() for b in text_blocks)
                if combined.strip():
                    display = (
                        combined[:200] + "..." if len(combined) > 200 else combined
                    )
                    print(f"  💬  {display}")

            if not tool_uses:
                if response.stop_reason == "end_turn" and not finalized:
                    print("  ⚠️  No tool calls. Nudging...")
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": build_nudge_prompt()}
                            ],
                        }
                    )
                    continue
                break

            # Add assistant response with tool uses
            messages.append({"role": "assistant", "content": response.content})

            # Execute tools and build tool_result blocks
            tool_results: list[dict] = []
            rendered_path: Path | None = None

            for tu in tool_uses:
                args = tu.input if tu.input else {}
                result, rpath, is_final = execute_tool(
                    self.scene, tu.name, args, self.output_stem
                )

                # Build result content
                result_content: list[dict] = [{"type": "text", "text": str(result)}]

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": result_content,
                    }
                )

                if rpath:
                    rendered_path = rpath
                if is_final:
                    finalized = True
                    final_glb_path = result.get("path", "")
                    status = "success"

            # Build user message with tool results
            user_content: list[dict] = tool_results

            # If we rendered, add the image and review prompt
            if rendered_path:
                img_bytes = read_image_bytes(rendered_path)
                user_content.append(
                    {"type": "text", "text": "**RENDERED RESULT**:"}
                )
                user_content.append(_make_image_block(img_bytes, "image/png"))
                user_content.append(
                    {
                        "type": "text",
                        "text": build_review_prompt(iteration, self.max_iterations),
                    }
                )

            messages.append({"role": "user", "content": user_content})

            if finalized:
                print("\n  ✅  Scene finalized!")
                break

        if not finalized:
            print(f"\n  ⚠️  Max iterations. Force-exporting...")
            final_glb_path = self.scene.export_scene(f"{self.output_stem}_final.glb")

        # Final preview render
        final_preview_path = self.scene.render_multi_view()
        self.cleanup()

        print(f"\n  🏁  Done. Output: {self.output_dir}/")

        return {
            "glb_path": str(final_glb_path),
            "preview_path": str(final_preview_path),
            "iterations": iteration,
            "status": status,
        }