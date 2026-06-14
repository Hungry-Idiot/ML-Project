import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")
model = os.getenv("MODEL_NAME")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY is missing in .env")
if not model:
    raise RuntimeError("MODEL_NAME is missing in .env")

client = OpenAI(
    api_key=api_key,
    base_url=base_url if base_url else None
)

resp = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "user", "content": "Please answer exactly: API works."}
    ],
    temperature=0,
    max_tokens=50,
)

print(resp.choices[0].message.content)