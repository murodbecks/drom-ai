from backend.drom_agent import DromAgent

agent = DromAgent(provider="claude")
result = agent.run(
    image_path="backend/drom_agent/assets/03_sample.jpg",
    objects={
        "cat": "backend/drom_agent/assets/03_cat.glb",
        "table": "backend/drom_agent/assets/03_table.glb",
        "mouse": "backend/drom_agent/assets/03_mouse.glb",
    },
    output_path="room_scene.glb",
)

print(f"GLB saved to: {result['glb_path']}")
print(f"Preview: {result['preview_path']}")
print(f"Iterations: {result['iterations']}")
print(f"Status: {result['status']}")