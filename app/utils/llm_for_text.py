import requests
import json
import os
from dotenv import load_dotenv
from openai import OpenAI
def generate_text_gemini(prompt):
    # Load environment variables from .env file
    load_dotenv()
    
    # Get API key from environment variables
    API_KEY = os.environ.get("GEMINI_API_KEY")
    
    # Endpoint URL
    # url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={API_KEY}"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={API_KEY}"
    # Headers
    headers = {
        "Content-Type": "application/json"
    }
    
    # Payload
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    
    try:
        # Send POST request
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        if response.status_code == 200:
            response_data = response.json()
            # Extract the generated text from the response
            # Assuming the response structure contains the generated text
            message_content = response_data['candidates'][0]['content']['parts'][0]['text']
            # print(prompt)
            print("--------------------------------")
            # print(message_content)
            return message_content
        else:
            print(f"Error: {response.status_code}")
    
            return None
            
    except Exception as e:
        print(f"Error during API call: {e}")
        return None
    

def generate_text(prompt, model="gpt-4o-mini"):
    # Load environment variables from .env file
    load_dotenv()

    # Initialize the OpenAI client with API Key
    print(os.environ.get("OPENAI_API_KEY"))
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

