from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

completion = client.chat.completions.create(
  model="gpt-4o",
  messages=[
    {"role": "developer", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What are five ways to improve my code quality?"}
  ]
)

print(completion.choices[0].message)
