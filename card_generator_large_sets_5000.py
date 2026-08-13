import json
import os
import time
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

def generate_flashcard_set(set_number, previous_words=None, max_retries=3, timeout=300):  # 300 seconds = 5 minutes
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

    for attempt in range(max_retries):
        try:
            start_time = time.time()
            response = generate_text(prompt)
            elapsed_time = time.time() - start_time
            
            if elapsed_time > timeout:
                print(f"Generation timed out after {elapsed_time:.2f} seconds. Attempt {attempt + 1} of {max_retries}")
                if attempt < max_retries - 1:
                    print("Retrying...")
                    continue
                else:
                    print("Max retries reached. Moving to next set.")
                    return None
            
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
                if attempt < max_retries - 1:
                    print("Retrying...")
                    continue
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
            print(f"Error processing set {set_number} (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                print("Retrying...")
                continue
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

def main():
    # Create flashcard_sets directory if it doesn't exist
    os.makedirs("flashcard_sets", exist_ok=True)
    
    # Initialize variables
    all_sets = []
    previous_words = set()
    current_word_count = 0
    target_word_count = 5000
    words_per_set = 100
    current_thousand_set = []
    
    # Find all existing sets
    existing_sets = []
    for filename in os.listdir("flashcard_sets"):
        if filename.startswith("common_words_set_") and filename.endswith(".json"):
            try:
                set_number = int(filename.replace("common_words_set_", "").replace(".json", ""))
                existing_sets.append(set_number)
            except ValueError:
                continue
    
    # Sort the set numbers to process them in order
    existing_sets.sort()
    
    # Read existing sets if they exist
    for set_number in existing_sets:
        filename = f"flashcard_sets/common_words_set_{set_number}.json"
        if os.path.exists(filename):
            print(f"Reading existing set {set_number}")
            with open(filename, 'r', encoding='utf-8') as f:
                set_data = json.load(f)
                all_sets.append(set_data)
                current_thousand_set.append(set_data)
                for card in set_data["cards"]:
                    previous_words.add(card["word"])
                    current_word_count += 1
    
    print(f"Found {len(existing_sets)} existing sets with {current_word_count} words")
    
    # Generate new sets until we reach 5000 words
    set_number = max(existing_sets) + 1 if existing_sets else 1
    while current_word_count < target_word_count:
        print(f"Generating set {set_number} of {target_word_count // words_per_set}")
        set_data = generate_flashcard_set(set_number, list(previous_words))
        
        if set_data:
            # Update previous words with new words from this set
            for card in set_data["cards"]:
                previous_words.add(card["word"])
                current_word_count += 1
            
            # Save individual set
            filename = f"flashcard_sets/common_words_set_{set_number}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(set_data, f, ensure_ascii=False, indent=2)
            print(f"Saved set to {filename}")
            
            all_sets.append(set_data)
            current_thousand_set.append(set_data)
            
            # Save combined set every 1000 words
            if current_word_count % 1000 == 0:
                # Save the current 1000-word set
                thousand_set = combine_flashcard_sets(current_thousand_set)
                thousand_set["name"] = f"Spanish Common Words Set {current_word_count//1000}"
                thousand_set["description"] = f"Set {current_word_count//1000} of 5 - {current_word_count-999} to {current_word_count} most common Spanish words"
                thousand_filename = f"flashcard_sets/set_{current_word_count//1000}_of_5.json"
                with open(thousand_filename, 'w', encoding='utf-8') as f:
                    json.dump(thousand_set, f, ensure_ascii=False, indent=2)
                print(f"Saved thousand-word set to {thousand_filename}")
                
                # Reset the current thousand set
                current_thousand_set = []
        
        set_number += 1
    
    # Save the final combined set of all 5000 words
    final_combined_set = combine_flashcard_sets(all_sets)
    final_combined_set["name"] = "5000 Most Common Spanish Words"
    final_combined_set["description"] = "A comprehensive set of the 5000 most common Spanish words, including nouns, verbs, adjectives, and other parts of speech"
    with open("flashcard_sets/5000_common_words_complete.json", 'w', encoding='utf-8') as f:
        json.dump(final_combined_set, f, ensure_ascii=False, indent=2)
    print("Saved final combined set to flashcard_sets/5000_common_words_complete.json")
    
    print(f"Total unique words generated: {len(previous_words)}")
    print(f"Final word count: {current_word_count}")

if __name__ == "__main__":
    main()
