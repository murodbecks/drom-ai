from backend.drom_agent import DromAgent

agent = DromAgent(provider="gemini")
result = agent.run(
    image_path="sample/pikachu-scene.jpeg",
    objects={
        "pikachu": "sample/pikachu.glb",
        "eeve": "sample/eevee.glb",
        "tree_stunt": "sample/tree_stunt.glb",
    },
    output_path="sample/pikachu_result.glb",
)

print(f"GLB saved to: {result['glb_path']}")
print(f"Preview: {result['preview_path']}")
print(f"Iterations: {result['iterations']}")
print(f"Status: {result['status']}")