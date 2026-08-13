import os
import csv
import json
import base64
import imghdr
from dotenv import load_dotenv
from openai import OpenAI

import io
from flask import jsonify

load_dotenv()

# Get the API key
openai_api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI(api_key=openai_api_key)


def get_image_type(image_path):
    """Determine the image type of a given file."""
    with open(image_path, 'rb') as f:
        image_type = imghdr.what(f)
    return image_type


def encode_image_to_base64(image_path_or_data):
    """Encode image to base64, supporting both file paths and binary data."""
    if isinstance(image_path_or_data, str):  # It's a file path
        with open(image_path_or_data, "rb") as image_file:
            image_data = image_file.read()
            image_type = get_image_type(image_path_or_data)
    else:  # It's binary data
        image_data = image_path_or_data
        image_type = imghdr.what(None, h=image_data)

    base64_image = base64.b64encode(image_data).decode('utf-8')
    return f"data:image/{image_type};base64,{base64_image}"


def analyze_menu_images_categories(image_data_list):
    """Analyze the menu image using the OpenAI API."""
    image_contents = [
        {
            "type": "image_url",
            "image_url": {
                "url": encode_image_to_base64(image_data),
            },
        } for image_data in image_data_list
    ]
    prompt = """
    Analyze this menu image and extract the following information:
    - Category names
    - Items in each category

    Return the information in this JSON format, and return only the JSON:

    {
      "categories": [
        {
          "name": "CLASSICS",
          "items": [
            "Classic Breakfast",
            "Griddle Platter",
            "The Big Boy"
          ]
        },
        {
          "name": "SKILLETS",
          "items": [
            "Garden Skillet",
            "Butcher Block Meat Lovers",
            "Rocky Mountain High"
          ]
        }
      ]
    }
    """

    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt}] + image_contents
        }
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )

    output = response.choices[0].message.content
    output = output.replace('```json\n', '').replace('\n```', '')
    menu_data = json.loads(output)

    return menu_data
