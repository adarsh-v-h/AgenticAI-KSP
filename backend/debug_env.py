import os
from dotenv import load_dotenv

dotenv_path = r"C:\Users\navaneeth\AgenticAI-KSP-v2\.env"
print(f"Loading from: {dotenv_path}")
print(f"File exists: {os.path.exists(dotenv_path)}")

result = load_dotenv(dotenv_path=dotenv_path, override=True, verbose=True)
print(f"load_dotenv returned: {result}")

print(f"CATALYST_PROJECT_ID = {repr(os.getenv('CATALYST_PROJECT_ID'))}")
print(f"CATALYST_API_TOKEN  = {repr(os.getenv('CATALYST_API_TOKEN'))[:40]}...")

# Also check for duplicate/conflicting definitions in the raw file
print("\n--- Raw lines containing CATALYST_PROJECT_ID ---")
with open(dotenv_path, "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "CATALYST_PROJECT_ID" in line:
            print(f"Line {i}: {repr(line)}")
