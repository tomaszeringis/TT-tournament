import os
print("Environment Variables:")
for k, v in os.environ.items():
    if "OLLAMA" in k or "MODEL" in k:
        print(f"{k}: {v}")
