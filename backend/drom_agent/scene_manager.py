"""Manages loading, transforming, rendering, and exporting a 3D scene."""

import os
import platform as _platform
import itertools
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

if _platform.system() != "Darwin":
    os.environ["PYOPENGL_PLATFORM"] = "egl"

import pyrender  # noqa: E402


class SceneManager:
    """Manages loading, transforming, rendering, and exporting a 3D scene."""

    def __init__(self, output_dir: str | Path = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.objects: dict[str, trimesh.Scene | trimesh.Trimesh] = {}
        self.positions: dict[str, list[float]] = {}
        self.rotations_deg: dict[str, list[float]] = {}
        self.scales: dict[str, list[float]] = {}
        self.step_counter = 0

        # Reusable renderers keyed by (width, height)
        self._renderers: dict[tuple[int, int], pyrender.OffscreenRenderer] = {}

    def _get_renderer(self, width: int, height: int) -> pyrender.OffscreenRenderer:
        key = (width, height)
        if key not in self._renderers:
            self._renderers[key] = pyrender.OffscreenRenderer(width, height)
        return self._renderers[key]

    def cleanup(self):
        """Call when done to release OpenGL resources."""
        for r in self._renderers.values():
            try:
                r.delete()
            except Exception:
                pass
        self._renderers.clear()

    # ── loading ───────────────────────────────────────────────────────

    def load_object(self, name: str, path: str | Path) -> dict:
        """Load a GLB file as a named object."""
        path = Path(path)
        obj = trimesh.load(str(path), force="scene")
        self.objects[name] = obj
        self.positions[name] = [0.0, 0.0, 0.0]
        self.rotations_deg[name] = [0.0, 0.0, 0.0]
        self.scales[name] = [1.0, 1.0, 1.0]

        bounds = np.array(obj.bounds)
        size = (bounds[1] - bounds[0]).tolist()
        center = ((bounds[0] + bounds[1]) / 2).tolist()

        return {
            "status": "loaded",
            "name": name,
            "size_xyz": size,
            "center_xyz": center,
            "bounds_min": bounds[0].tolist(),
            "bounds_max": bounds[1].tolist(),
        }

    # ── transforms ────────────────────────────────────────────────────

    def set_position(self, name: str, x: float, y: float, z: float) -> dict:
        if name not in self.objects:
            return {"error": f"Object '{name}' not found"}
        self.positions[name] = [x, y, z]
        return {"status": "ok", "name": name, "position": [x, y, z]}

    def set_rotation(self, name: str, rx: float, ry: float, rz: float) -> dict:
        if name not in self.objects:
            return {"error": f"Object '{name}' not found"}
        self.rotations_deg[name] = [rx, ry, rz]
        return {"status": "ok", "name": name, "rotation_deg": [rx, ry, rz]}

    def set_scale(self, name: str, sx: float, sy: float, sz: float) -> dict:
        if name not in self.objects:
            return {"error": f"Object '{name}' not found"}
        self.scales[name] = [sx, sy, sz]
        return {"status": "ok", "name": name, "scale": [sx, sy, sz]}

    def get_object_info(self, name: str) -> dict:
        if name not in self.objects:
            return {"error": f"Object '{name}' not found"}
        obj = self.objects[name]
        bounds = np.array(obj.bounds)
        return {
            "name": name,
            "position": self.positions[name],
            "rotation_deg": self.rotations_deg[name],
            "scale": self.scales[name],
            "size_xyz": (bounds[1] - bounds[0]).tolist(),
        }

    def get_scene_info(self) -> dict:
        return {name: self.get_object_info(name) for name in self.objects}

    # ── internal helpers ──────────────────────────────────────────────

    def _build_transform(self, name: str) -> np.ndarray:
        pos = self.positions[name]
        rot = [np.radians(a) for a in self.rotations_deg[name]]
        scl = self.scales[name]

        T = trimesh.transformations.translation_matrix(pos)
        Rx = trimesh.transformations.rotation_matrix(rot[0], [1, 0, 0])
        Ry = trimesh.transformations.rotation_matrix(rot[1], [0, 1, 0])
        Rz = trimesh.transformations.rotation_matrix(rot[2], [0, 0, 1])
        R = Rz @ Ry @ Rx
        S = np.diag([scl[0], scl[1], scl[2], 1.0])

        return T @ R @ S

    def _gather_trimeshes(
        self, obj: trimesh.Scene | trimesh.Trimesh
    ) -> list[trimesh.Trimesh]:
        if isinstance(obj, trimesh.Trimesh):
            return [obj]
        meshes: list[trimesh.Trimesh] = []
        for geo in obj.geometry.values():
            if isinstance(geo, trimesh.Trimesh):
                meshes.append(geo)
        return meshes

    def _scene_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        all_pts: list[np.ndarray] = []
        for name, obj in self.objects.items():
            transform = self._build_transform(name)
            bounds = np.array(obj.bounds)
            mn, mx = bounds[0], bounds[1]
            corners = np.array(
                list(itertools.product(*zip(mn.tolist(), mx.tolist())))
            )
            ones = np.ones((corners.shape[0], 1))
            corners_h = np.hstack([corners, ones])
            world = (transform @ corners_h.T).T[:, :3]
            all_pts.append(world)
        if not all_pts:
            return np.zeros(3), np.ones(3)
        all_pts_arr = np.vstack(all_pts)
        return all_pts_arr.min(axis=0), all_pts_arr.max(axis=0)

    def _build_pyrender_scene(self) -> pyrender.Scene:
        pr_scene = pyrender.Scene(
            ambient_light=[0.4, 0.4, 0.4],
            bg_color=[0.92, 0.92, 0.92, 1.0],
        )
        for name, obj in self.objects.items():
            transform = self._build_transform(name)
            for mesh in self._gather_trimeshes(obj):
                pr_mesh = pyrender.Mesh.from_trimesh(mesh, smooth=True)
                pr_scene.add(pr_mesh, pose=transform)
        return pr_scene

    def _camera_pose_from_direction(
        self,
        center: np.ndarray,
        direction: np.ndarray,
        distance: float,
    ) -> np.ndarray:
        cam_pos = center + direction * distance
        forward = center - cam_pos
        norm = np.linalg.norm(forward)
        if norm < 1e-8:
            forward = np.array([0.0, 0.0, -1.0])
        else:
            forward /= norm

        world_up = np.array([0.0, 1.0, 0.0])
        if abs(np.dot(forward, world_up)) > 0.99:
            world_up = np.array([0.0, 0.0, -1.0])

        right = np.cross(forward, world_up)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)

        pose = np.eye(4)
        pose[:3, 0] = right
        pose[:3, 1] = up
        pose[:3, 2] = -forward
        pose[:3, 3] = cam_pos
        return pose

    def _render_single_view(
        self,
        center: np.ndarray,
        direction: np.ndarray,
        distance: float,
        width: int,
        height: int,
    ) -> np.ndarray:
        """Render a single view and return the color array."""
        direction = direction / np.linalg.norm(direction)
        cam_pose = self._camera_pose_from_direction(center, direction, distance)

        pr_scene = self._build_pyrender_scene()
        camera = pyrender.PerspectiveCamera(yfov=np.pi / 3.5)
        pr_scene.add(camera, pose=cam_pose)

        light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=5.0)
        pr_scene.add(light, pose=cam_pose)

        fill_dir = np.array([-0.5, 0.3, -0.2])
        fill_dir /= np.linalg.norm(fill_dir)
        fill_pose = self._camera_pose_from_direction(center, fill_dir, distance * 0.8)
        fill = pyrender.PointLight(color=[1.0, 1.0, 0.95], intensity=15.0)
        pr_scene.add(fill, pose=fill_pose)

        renderer = self._get_renderer(width, height)
        color, _ = renderer.render(pr_scene)
        return color

    def _get_font(self, size: int = 24) -> ImageFont.FreeTypeFont:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNSMono.ttf",
            "Arial Bold.ttf",
        ]
        for fp in font_paths:
            try:
                return ImageFont.truetype(fp, size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    # ── rendering ─────────────────────────────────────────────────────

    def render_scene(self, width: int = 1024, height: int = 768) -> str:
        scene_min, scene_max = self._scene_bounds()
        center = (scene_min + scene_max) / 2
        extent = np.linalg.norm(scene_max - scene_min)
        dist = max(float(extent) * 1.8, 5.0)

        direction = np.array([0.3, 0.5, 0.8])
        color = self._render_single_view(center, direction, dist, width, height)

        self.step_counter += 1
        path = self.output_dir / f"step_{self.step_counter:03d}.png"
        Image.fromarray(color).save(str(path))
        print(f"  📸  Rendered → {path}")
        return str(path)

    def render_multi_view(self, width: int = 768, height: int = 576) -> str:
        scene_min, scene_max = self._scene_bounds()
        center = (scene_min + scene_max) / 2
        extent = np.linalg.norm(scene_max - scene_min)
        dist = max(float(extent) * 2.0, 6.0)

        views = {
            "Front": np.array([0.0, 0.0, 1.0]),
            "Right Side": np.array([1.0, 0.0, 0.0]),
            "Top Down": np.array([0.0, 1.0, 0.001]),
            "Sketch Angle": np.array([0.3, 0.5, 0.8]),
        }

        font = self._get_font(24)
        images: list[Image.Image] = []

        for label, direction in views.items():
            color = self._render_single_view(center, direction, dist, width, height)
            img = Image.fromarray(color)

            draw = ImageDraw.Draw(img)
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            pad = 6
            draw.rectangle(
                [8, 8, 8 + tw + pad * 2, 8 + th + pad * 2],
                fill=(0, 0, 0, 180),
            )
            draw.text(
                (8 + pad, 8 + pad),
                label,
                fill=(255, 255, 255),
                font=font,
            )
            images.append(img)

        grid_w = width * 2
        grid_h = height * 2
        grid = Image.new("RGB", (grid_w, grid_h), (235, 235, 235))
        grid.paste(images[0], (0, 0))
        grid.paste(images[1], (width, 0))
        grid.paste(images[2], (0, height))
        grid.paste(images[3], (width, height))

        self.step_counter += 1
        path = self.output_dir / f"step_{self.step_counter:03d}_multiview.png"
        grid.save(str(path), quality=90)
        print(f"  📸  Multi-view rendered → {path}")
        return str(path)

    # ── export ────────────────────────────────────────────────────────

    def export_scene(self, filename: str = "final_scene.glb") -> str:
        combined = trimesh.Scene()
        for name, obj in self.objects.items():
            transform = self._build_transform(name)
            for i, mesh in enumerate(self._gather_trimeshes(obj)):
                mesh_copy = mesh.copy()

                # Fix vertex colors to prevent export errors
                if hasattr(mesh_copy, "visual") and hasattr(
                    mesh_copy.visual, "vertex_colors"
                ):
                    try:
                        vc = mesh_copy.visual.vertex_colors
                        if vc is not None:
                            vc = np.asarray(vc)
                            n_verts = len(mesh_copy.vertices)
                            # Only keep if it's already in correct shape
                            if vc.shape != (n_verts, 4):
                                mesh_copy.visual.vertex_colors = None
                    except Exception:
                        pass

                combined.add_geometry(
                    mesh_copy,
                    node_name=f"{name}_{i}",
                    transform=transform,
                )

        path = self.output_dir / filename
        combined.export(str(path))
        print(f"  💾  Exported → {path}")
        return str(path)