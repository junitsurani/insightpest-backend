from dotenv import load_dotenv
from openai import OpenAI
import os


def generate_text(prompt, model="gpt-4o-2024-05-13"):
    # Load environment variables from .env file
    load_dotenv()

    # Initialize the OpenAI client with API Key
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    try:
        # Create a chat completion
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
        )

        # Access the message content
        message_content = chat_completion.choices[0].message.content
        message_content = message_content.replace('```python\n', '').replace('```json\n', '').replace('```jsx\n',
                                                                                                      '').replace(
            '```javascript\n', '').replace('\n```', '')
        return message_content
    except Exception as e:
        print(f"Error during API call: {e}")
        return None
