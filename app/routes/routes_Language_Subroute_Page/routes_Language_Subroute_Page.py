from flask import jsonify, Blueprint, request
from app.models import db
from app.models.user import User, LanguageSession, LanguageGoal, FlashcardSet, Flashcard, GeneratedStory
from datetime import datetime, timedelta
import json
import threading
from flask import current_app
api_Language_Subroute_Page = Blueprint("api_Language_Subroute_Page", __name__, url_prefix="")

@api_Language_Subroute_Page.route('/flashcards/<username>', methods=['GET'])
def get_flashcard_sets(username):
    try:
        sets = FlashcardSet.query.filter_by(username=username).all()
        return jsonify([set.to_dict() for set in sets])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_Language_Subroute_Page.route('/flashcards/<username>', methods=['POST'])
def create_flashcard_set(username):
    try:
        data = request.get_json()
        print("Received data:", data)  # Debug log
        
        # Create new flashcard set
        new_set = FlashcardSet(
            username=username,
            name=data['name'],
            description=data['description'],
            completed=False
        )
        db.session.add(new_set)
        db.session.flush()  # Get the ID of the new set
        
        # Create flashcards
        for card_data in data['cards']:
            print("Processing card:", card_data)  # Debug log
            new_card = Flashcard(
                set_id=new_set.id,
                word=card_data['word'],
                irregular_forms=card_data.get('irregularForms'),
                sentence=card_data['sentence'],
                word_translation=card_data['wordTranslation'],
                sentence_translation=card_data['sentenceTranslation'],
                learned=False
            )
            db.session.add(new_card)
        
        db.session.commit()
        result = new_set.to_dict()
        print("Returning result:", result)  # Debug log
        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        print("Error:", str(e))  # Debug log
        return jsonify({'error': str(e)}), 500

@api_Language_Subroute_Page.route('/flashcards/<username>/<int:set_id>', methods=['GET'])
def get_flashcard_set(username, set_id):
    try:
        flashcard_set = FlashcardSet.query.filter_by(username=username, id=set_id).first()
        if not flashcard_set:
            return jsonify({'error': 'Flashcard set not found'}), 404
        result = flashcard_set.to_dict()
        print("Returning flashcard set:", result)  # Debug log
        return jsonify(result)
    except Exception as e:
        print("Error:", str(e))  # Debug log
        return jsonify({'error': str(e)}), 500

@api_Language_Subroute_Page.route('/flashcards/<username>/<int:set_id>/<int:card_id>/learned', methods=['PUT'])
def update_card_learned_status(username, set_id, card_id):
    try:
        card = Flashcard.query.join(FlashcardSet).filter(
            FlashcardSet.username == username,
            FlashcardSet.id == set_id,
            Flashcard.id == card_id
        ).first()
        
        if not card:
            return jsonify({'error': 'Card not found'}), 404
            
        data = request.get_json()
        card.learned = data.get('learned', False)
        
        # Update set completion status
        set = card.set
        set.completed = all(c.learned for c in set.cards)
        
        db.session.commit()
        return jsonify(card.set.to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@api_Language_Subroute_Page.route('/flashcards/<username>/<int:set_id>', methods=['DELETE'])
def delete_flashcard_set(username, set_id):
    print(f"=== DELETE FLASHCARD SET REQUEST ===")
    print(f"Username from URL: {username}")
    print(f"Set ID: {set_id}")
    
    try:
        data = request.get_json()
        print(f"Request data: {data}")
        request_username = data.get('username') if data else None
        print(f"Username from request body: {request_username}")
        
        # Use username from request body if provided, otherwise from URL
        target_username = request_username or username
        print(f"Target username: {target_username}")
        
        # Find the flashcard set and verify it belongs to the user
        flashcard_set = FlashcardSet.query.filter_by(username=target_username, id=set_id).first()
        
        if not flashcard_set:
            print(f"Flashcard set not found for username: {target_username}, set_id: {set_id}")
            return jsonify({'error': 'Flashcard set not found'}), 404
        
        print(f"Found flashcard set: {flashcard_set.name} with {len(flashcard_set.cards)} cards")
        
        # Use bulk delete for better performance with large sets
        # Delete all flashcards in the set using bulk delete
        Flashcard.query.filter_by(set_id=set_id).delete()
        
        # Delete the flashcard set
        print(f"Deleting flashcard set: {flashcard_set.name}")
        db.session.delete(flashcard_set)
        db.session.commit()
        
        print("Flashcard set deleted successfully")
        return jsonify({'message': 'Flashcard set deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting flashcard set: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api_Language_Subroute_Page.route('/stories/<username>', methods=['GET'])
def get_stories(username):
    try:
        stories = GeneratedStory.query.filter_by(username=username).all()
        return jsonify([story.to_dict() for story in stories])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_Language_Subroute_Page.route('/stories/<username>/<int:story_id>', methods=['GET'])
def get_story(username, story_id):
    try:
        story = GeneratedStory.query.filter_by(username=username, id=story_id).first()
        if not story:
            return jsonify({'error': 'Story not found'}), 404

        # Get the story data
        story_data = story.to_dict()
        
        # Calculate learned words from flashcard sets
        learned_words_count = 0
        total_words = 0
        used_sets = json.loads(story.used_flashcard_sets) if story.used_flashcard_sets else []
        
        for set_id in used_sets:
            flashcard_set = FlashcardSet.query.get(set_id)
            if flashcard_set and flashcard_set.username == username:
                for card in flashcard_set.cards:
                    total_words += 1
                    if card.learned:
                        learned_words_count += 1

        # Add learned words information to the response
        story_data['learnedWordsCount'] = learned_words_count
        story_data['totalWords'] = total_words
        
        return jsonify(story_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_Language_Subroute_Page.route('/generate-story', methods=['POST'])
def generate_story():
    try:
        data = request.get_json()
        username = data.get('username')
        prompt = data.get('prompt', '')
        flashcard_set_ids = data.get('flashcardSetIds', [])
        word_count = data.get('wordCount', 500)  # Default to 500 if not specified

        # Get all words from selected flashcard sets
        all_words = []
        for set_id in flashcard_set_ids:
            flashcard_set = FlashcardSet.query.get(set_id)
            if flashcard_set and flashcard_set.username == username:
                for card in flashcard_set.cards:
                    all_words.append({
                        'word': card.word,
                        'translation': card.word_translation,
                        'sentence': card.sentence,
                        'sentence_translation': card.sentence_translation
                    })

        # Create initial story record
        new_story = GeneratedStory(
            username=username,
            title="Generating...",
            content="",
            prompt=prompt,
            used_flashcard_sets=json.dumps(flashcard_set_ids),
            total_words_used=len(all_words),
            status='processing'
        )
        
        db.session.add(new_story)
        db.session.commit()

        # Prepare prompt for LLM
        words_text = "\n".join([
            f"Word: {w['word']} (Translation: {w['translation']})\nExample: {w['sentence']}"
            for w in all_words
        ])
        
        llm_prompt = f"""Create a story in Spanish using ONLY the following vocabulary words. 
        The story must ONLY use these exact words and their variations (conjugations, gender agreements, etc.).
        Do not use any other Spanish words that are not in this list.
        
        If a prompt/theme is provided, incorporate it while still using ONLY these words.
        
        Vocabulary words to use (with translations and example sentences):
        {words_text}
        
        Theme/Prompt: {prompt}
        
        Target length: {word_count} words
        
        Important instructions:
        1. Use ONLY the words provided above
        2. You can use different forms of these words (conjugations, gender agreements)
        3. Do not add any new words that aren't in the list
        4. The first line should be the title
        5. Provide the output in plain text format only
        6. Make sure the story is coherent and engaging while following these constraints
        7. You can use basic words like "el", "la", "los", "las", "un", "una", "unos", "unas", etc.
        8. If there's not enough words to create a story, you can use the words to create a poem or a short story or repeat the words in a creative way.
        9. If there are not enough nouns, keep the story simple and focus on the verbs and adjectives do not innclude words not in the list.
        10. Try to make the story approximately {word_count} words long
        
        Please provide the story in Spanish with a title. Do not use any markdown formatting or special characters."""

        app = current_app._get_current_object()
        start_thread_generate_story(app, username, llm_prompt, all_words, flashcard_set_ids, new_story.id)
        
        return jsonify({'message': 'Story generation started', 'storyId': new_story.id}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


def start_thread_generate_story(app, username, llm_prompt, all_words, flashcard_set_ids, story_id):
    thread = threading.Thread(target=generate_story_thread, args=(app, username, llm_prompt, all_words, flashcard_set_ids, story_id))
    thread.start()


def generate_story_thread(app, username, llm_prompt, all_words, flashcard_set_ids, story_id):
    with app.app_context():
        try:
            from app.utils.llm_for_text import generate_text
            generated_text = generate_text(llm_prompt)
            
            if not generated_text:
                story = GeneratedStory.query.get(story_id)
                if story:
                    story.status = 'failed'
                    db.session.commit()
                return

            # Split the generated text into title and content
            lines = generated_text.strip().split('\n')
            title = lines[0].strip()
            content = '\n'.join(lines[1:]).strip()

            # Update the story
            story = GeneratedStory.query.get(story_id)
            if story:
                story.title = title
                story.content = content
                story.status = 'completed'
                db.session.commit()
        except Exception as e:
            story = GeneratedStory.query.get(story_id)
            if story:
                story.status = 'failed'
                db.session.commit()
            print(f"Error generating story: {str(e)}")


@api_Language_Subroute_Page.route('/stories/<username>/<int:story_id>/status', methods=['GET'])
def get_story_status(username, story_id):
    try:
        story = GeneratedStory.query.filter_by(username=username, id=story_id).first()
        if not story:
            return jsonify({'error': 'Story not found'}), 404
        return jsonify({
            'status': story.status,
            'story': story.to_dict() if story.status == 'completed' else None
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_Language_Subroute_Page.route('/flashcards/<username>/stats', methods=['GET'])
def get_flashcard_stats(username):
    try:
        # Get all flashcard sets for the user
        flashcard_sets = FlashcardSet.query.filter_by(username=username).all()
        
        total_words = 0
        learned_words = 0
        
        for flashcard_set in flashcard_sets:
            for card in flashcard_set.cards:
                total_words += 1
                if card.learned:
                    learned_words += 1
        
        return jsonify({
            'totalWords': total_words,
            'learnedWords': learned_words
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

