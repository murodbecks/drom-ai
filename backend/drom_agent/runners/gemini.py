"""Gemini-based runner."""

import os
from pathlib import Path

from google import genai
from google.genai import types

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


def _to_gemini_schema(props: dict) -> dict[str, types.Schema]:
    """Convert our schema properties to Gemini Schema objects."""
    result = {}
    for key, val in props.items():
        schema_type = val.get("type", "string").upper()
        result[key] = types.Schema(
            type=schema_type, description=val.get("description", "")
        )
    return result


def _build_gemini_tools() -> list[types.Tool]:
    """Convert generic tool schema to Gemini format."""
    declarations = []
    for tool in TOOLS_SCHEMA:
        params = tool["parameters"]
        declarations.append(
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=types.Schema(
                    type="OBJECT",
                    properties=_to_gemini_schema(params.get("properties", {})),
                    required=params.get("required", []),
                ),
            )
        )
    return [types.Tool(function_declarations=declarations)]


class GeminiRunner(BaseRunner):
    """Gemini-powered scene reconstruction."""

    def __init__(
        self,
        image_path: Path,
        objects: dict[str, Path],
        output_dir: Path,
        output_stem: str,
        max_iterations: int = 15,
        model: str = "gemini-2.5-flash",
    ):
        super().__init__(
            image_path, objects, output_dir, output_stem, max_iterations
        )
        self.model = model
        self.client = genai.Client(
            vertexai=True,
            project=os.environ.get("GCLOUD_PROJECT_ID"),
            location="global",
        )

    def run(self) -> dict:
        print(f"  🤖  Provider: Gemini ({self.model})")
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

        # Build initial conversation
        contents: list[types.Content] = [
            types.Content(
                role="user",
                parts=[
                    types.Part(text="**REFERENCE SKETCH** (target layout):"),
                    types.Part(
                        inline_data=types.Blob(data=ref_bytes, mime_type=ref_mime)
                    ),
                    types.Part(text="**CURRENT STATE** (all objects at origin):"),
                    types.Part(
                        inline_data=types.Blob(
                            data=initial_bytes, mime_type="image/png"
                        )
                    ),
                    types.Part(text=initial_user_prompt),
                ],
            )
        ]

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=_build_gemini_tools(),
            temperature=0.2,
        )

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

            response = self.client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
            candidate = response.candidates[0]

            # Extract function calls
            function_calls = [
                p.function_call for p in candidate.content.parts if p.function_call
            ]

            # Print any text (truncated)
            text_parts = [p.text for p in candidate.content.parts if p.text]
            if text_parts:
                combined = " ".join(t.strip() for t in text_parts)
                if combined.strip():
                    display = (
                        combined[:200] + "..." if len(combined) > 200 else combined
                    )
                    print(f"  💬  {display}")

            if not function_calls:
                if not finalized:
                    print("  ⚠️  No tool calls. Nudging...")
                    contents.append(candidate.content)
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part(text=build_nudge_prompt())],
                        )
                    )
                    continue
                break

            contents.append(candidate.content)

            # Execute tools
            fn_response_parts: list[types.Part] = []
            rendered_path: Path | None = None

            for fc in function_calls:
                args = dict(fc.args) if fc.args else {}
                result, rpath, is_final = execute_tool(
                    self.scene, fc.name, args, self.output_stem
                )
                fn_response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name, response={"result": result}
                        )
                    )
                )
                if rpath:
                    rendered_path = rpath
                if is_final:
                    finalized = True
                    final_glb_path = result.get("path", "")
                    status = "success"

            user_parts: list[types.Part] = list(fn_response_parts)

            # If we rendered, add the image and review prompt
            if rendered_path:
                img_bytes = read_image_bytes(rendered_path)
                user_parts.append(types.Part(text="**RENDERED RESULT**:"))
                user_parts.append(
                    types.Part(
                        inline_data=types.Blob(data=img_bytes, mime_type="image/png")
                    )
                )
                user_parts.append(
                    types.Part(
                        text=build_review_prompt(iteration, self.max_iterations)
                    )
                )

            contents.append(types.Content(role="user", parts=user_parts))

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