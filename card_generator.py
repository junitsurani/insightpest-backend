import json
import os
from app.utils.llm_for_text import generate_text

def generate_flashcard_set(set_type, set_number):
    prompt = f"""Generate a JSON object for a Spanish flashcard set with the following specifications:
    - Set name should be descriptive of the content (e.g., "Spanish {set_type} Set {set_number}")
    - Description should explain the type of words included
    - Include exactly 20 cards
    - Each card should have:
        - word: the Spanish word
        - irregularForms: conjugation or variations if applicable (for verbs), otherwise null
        - sentence: an example sentence using the word
        - wordTranslation: English translation of the word
        - sentenceTranslation: English translation of the example sentence
    
    The set should focus on {set_type} and be appropriate for intermediate Spanish learners.
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
    
    Ensure the JSON is properly formatted and valid."""

    response = generate_text(prompt)
    try:
        # Extract JSON from the response
        json_str = response.strip()
        if json_str.startswith('```json'):
            json_str = json_str[7:]
        if json_str.endswith('```'):
            json_str = json_str[:-3]
        json_str = json_str.strip()
        
        return json.loads(json_str)
    except Exception as e:
        print(f"Error parsing JSON for set {set_number}: {str(e)}")
        return None

def combine_flashcard_sets(sets):
    combined = {
        "name": "Combined Spanish Vocabulary Set",
        "description": "A comprehensive set of Spanish vocabulary including verbs, nouns, and adjectives",
        "cards": []
    }
    
    for set_data in sets:
        if set_data and "cards" in set_data:
            combined["cards"].extend(set_data["cards"])
    
    return combined

def main():
    # Create flashcard_sets directory if it doesn't exist
    os.makedirs("flashcard_sets", exist_ok=True)
    
    # Generate 5 different sets
    set_types = ["Common Verbs", "Essential Nouns", "Descriptive Adjectives", 
                "Business Vocabulary", "Daily Activities"]
    
    all_sets = []
    
    for i, set_type in enumerate(set_types, 1):
        print(f"Generating set {i}: {set_type}")
        set_data = generate_flashcard_set(set_type, i)
        
        if set_data:
            # Save individual set
            filename = f"flashcard_sets/set_{i}_{set_type.lower().replace(' ', '_')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(set_data, f, ensure_ascii=False, indent=2)
            print(f"Saved set to {filename}")
            
            all_sets.append(set_data)
    
    # Combine all sets
    combined_set = combine_flashcard_sets(all_sets)
    
    # Save combined set
    with open("flashcard_sets/combined_set.json", 'w', encoding='utf-8') as f:
        json.dump(combined_set, f, ensure_ascii=False, indent=2)
    print("Saved combined set to flashcard_sets/combined_set.json")

if __name__ == "__main__":
    main()
