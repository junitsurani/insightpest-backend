import json
import os
from app.utils.llm_for_text import generate_text

def clean_json_response(response):
    """Clean and validate the JSON response from the LLM."""
    # Remove any markdown code block markers
    json_str = response.strip()
    if json_str.startswith('```json'):
        json_str = json_str[7:]
    if json_str.endswith('```'):
        json_str = json_str[:-3]
    json_str = json_str.strip()
    
    # Try to find the first '{' and last '}'
    start = json_str.find('{')
    end = json_str.rfind('}') + 1
    if start != -1 and end != 0:
        json_str = json_str[start:end]
    
    return json_str

def generate_flashcard_set(set_number, previous_words=None):
    # Create context from previous words if available
    context = ""
    if previous_words:
        context = f"Here are the words already generated (DO NOT REPEAT THESE): {', '.join(previous_words)}"
    
    prompt = f"""Generate a JSON object for a Spanish flashcard set with the following specifications:
    - Set name should be "Spanish Common Words Set {set_number}"
    - Description should explain this is part of a larger set of common Spanish words
    - Include exactly 100 cards
    - Each card should have:
        - word: the Spanish word (must be a common, frequently used word)
        - irregularForms: conjugation or variations if applicable (for verbs), otherwise null
        - sentence: an example sentence using the word
        - wordTranslation: English translation of the word
        - sentenceTranslation: English translation of the example sentence
    
    The set should include a mix of common nouns, verbs, adjectives, and other parts of speech.
    Focus on the most frequently used words in Spanish.
    {context}
    
    Format the response as a valid JSON object matching this structure:
    {{
        "name": "string",
        "description": "string",
        "cards": [
            {{
                "word": "string",
                "irregularForms": "string or null",
                "sentence": "string",
                "wordTranslation": "string",
                "sentenceTranslation": "string"
            }}
        ]
    }}
    
    IMPORTANT: Ensure the JSON is properly formatted and valid. Double-check all quotes and commas. ONLY RETURN THE JSON, NO OTHER TEXT."""

    response = generate_text(prompt)
    try:
        # Clean and validate the JSON response
        json_str = clean_json_response(response)
        
        # Try to parse the JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {str(e)}")
            print("First 100 characters of problematic JSON:")
            print(json_str[:100])
            print("\nLast 100 characters of problematic JSON:")
            print(json_str[-100:])
            raise
        
        # Validate the structure
        if not isinstance(data, dict):
            raise ValueError("Response is not a JSON object")
        if "name" not in data or "description" not in data or "cards" not in data:
            raise ValueError("Missing required fields in JSON response")
        if not isinstance(data["cards"], list):
            raise ValueError("'cards' field is not an array")
        
        # Validate each card
        for i, card in enumerate(data["cards"]):
            required_fields = ["word", "irregularForms", "sentence", "wordTranslation", "sentenceTranslation"]
            for field in required_fields:
                if field not in card:
                    raise ValueError(f"Card {i} is missing required field: {field}")
        
        return data
    except Exception as e:
        print(f"Error processing set {set_number}: {str(e)}")
        # Save the problematic response for debugging
        debug_file = f"flashcard_sets/error_set_{set_number}.txt"
        os.makedirs("flashcard_sets", exist_ok=True)
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write("Original response:\n")
            f.write(response)
            f.write("\n\nCleaned JSON:\n")
            f.write(json_str)
        print(f"Saved error details to {debug_file}")
        return None

def combine_flashcard_sets(sets):
    combined = {
        "name": "1000 Most Common Spanish Words",
        "description": "A comprehensive set of the 1000 most common Spanish words, including nouns, verbs, adjectives, and other parts of speech",
        "cards": []
    }
    
    for set_data in sets:
        if set_data and "cards" in set_data:
            combined["cards"].extend(set_data["cards"])
    
    return combined

def extract_words_from_file(file_path):
    """
    Extract words from a JSON flashcard file.
    
    Args:
        file_path (str): Path to the JSON file containing flashcards
        
    Returns:
        list: List of Spanish words from the flashcards
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        if not isinstance(data, dict) or 'cards' not in data:
            raise ValueError("Invalid flashcard file format")
            
        words = [card['word'] for card in data['cards']]
        return words
    except Exception as e:
        print(f"Error extracting words from {file_path}: {str(e)}")
        return []

def main():
    # Create flashcard_sets directory if it doesn't exist
    os.makedirs("flashcard_sets", exist_ok=True)
    
    # Generate 10 sets of 100 words each to get 1000 words total
    num_sets = 10
    all_sets = []
    previous_words = set()
    
    for i in range(1, num_sets + 1):
        print(f"Generating set {i} of {num_sets}")
        set_data = generate_flashcard_set(i, list(previous_words))
        
        if set_data:
            # Update previous words with new words from this set
            for card in set_data["cards"]:
                previous_words.add(card["word"])
            
            # Save individual set
            filename = f"flashcard_sets/common_words_set_{i}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(set_data, f, ensure_ascii=False, indent=2)
            print(f"Saved set to {filename}")
            
            all_sets.append(set_data)
    
    # Combine all sets
    combined_set = combine_flashcard_sets(all_sets)
    
    # Save combined set
    with open("flashcard_sets/1000_common_words.json", 'w', encoding='utf-8') as f:
        json.dump(combined_set, f, ensure_ascii=False, indent=2)
    print("Saved combined set to flashcard_sets/1000_common_words.json")
    print(f"Total unique words generated: {len(previous_words)}")

if __name__ == "__main__":
    # main()
    words = extract_words_from_file("flashcard_sets/1000_common_words.json")
    print(words)
