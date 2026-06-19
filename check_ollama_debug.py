import ollama
import json
try:
    resp = ollama.list()
    print("Ollama is running!")
    
    if hasattr(resp, 'models'):
        models = resp.models
    else:
        models = resp.get('models', [])
        
    print(f"Found {len(models)} models:")
    for model in models:
        if hasattr(model, 'model'):
            print(f" - {model.model}")
        elif isinstance(model, dict) and 'name' in model:
            print(f" - {model['name']}")
        else:
            print(f" - {model}")
except Exception as e:
    print(f"Error checking Ollama: {e}")
