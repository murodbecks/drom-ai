"""
Drom Agent - Sketch to 3D scene reconstruction.

Usage:
    from backend.drom_agent import DromAgent

    agent = DromAgent(provider="claude")
    result = agent.run(
        image_path="path/to/sketch.jpg",
        objects={"house": "path/to/house.glb", "table": "path/to/table.glb"},
        output_path="path/to/output.glb",  # optional
    )
"""

from .agent import DromAgent

__all__ = ["DromAgent"]
__version__ = "0.1.0"