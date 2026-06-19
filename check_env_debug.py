import os
import sys

print(f"Python: {sys.version}")
print(f"OLLAMA_MODEL env: {os.environ.get('OLLAMA_MODEL')}")
print("All OLLAMA env vars:")
for k, v in os.environ.items():
    if "OLLAMA" in k:
        print(f"  {k}: {v}")
