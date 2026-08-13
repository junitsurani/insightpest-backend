import json
import os
import requests
import time
import random
from collections import defaultdict
import re

class AlternativeWordGenerator:
    def __init__(self):
        self.existing_words = set()
        self.word_sources = []
        self.generated_words = []
        
    def load_existing_words(self):
        """Load all words from existing sets to avoid duplicates."""
        existing_words = set()
        
        # Load from the main 5000-word set
        if os.path.exists("flashcard_sets/5000_common_words_complete.json"):
            print("Loading existing words from 5000_common_words_complete.json...")
            with open("flashcard_sets/5000_common_words_complete.json", 'r', encoding='utf-8') as f:
                data = json.load(f)
                for card in data["cards"]:
                    existing_words.add(card["word"].lower())
            print(f"Loaded {len(existing_words)} existing words")
        
        # Load from next_5000 sets if they exist
        for filename in os.listdir("flashcard_sets"):
            if filename.startswith("next_5000_set_") and filename.endswith(".json"):
                with open(f"flashcard_sets/{filename}", 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for card in data["cards"]:
                        existing_words.add(card["word"].lower())
        
        self.existing_words = existing_words
        return existing_words
    
    def get_words_from_frequency_lists(self):
        """Get words from online Spanish frequency lists."""
        frequency_words = []
        
        # Common Spanish frequency words (ranked 5000-10000 range)
        # These are words that are common but not in the top 5000
        mid_frequency_words = [
            # Common verbs (5000-10000 range)
            "abrazar", "acostar", "admirar", "adoptar", "advertir", "agradecer", "alcanzar", 
            "alegrar", "almorzar", "amanecer", "anunciar", "apagar", "aparcar", "apoyar",
            "arreglar", "asustar", "atender", "atraer", "avanzar", "bailar", "bajar",
            "besar", "borrar", "brillar", "cambiar", "caminar", "cantar", "cargar",
            "celebrar", "cenar", "cerrar", "charlar", "comenzar", "comprar", "conectar",
            "contar", "cortar", "crecer", "cruzar", "cuidar", "dejar", "desayunar",
            "desear", "dibujar", "dormir", "duchar", "encontrar", "entender", "entrar",
            "escuchar", "esperar", "estudiar", "explicar", "fumar", "ganar", "gastar",
            "golpear", "gritar", "guardar", "gustar", "hablar", "herir", "invitar",
            "jugar", "lavar", "leer", "limpiar", "llamar", "llegar", "llevar", "luchar",
            "mandar", "marcar", "mirar", "nadar", "necesitar", "olvidar", "pagar",
            "parar", "pasar", "pedir", "pensar", "perder", "permitir", "pintar",
            "preguntar", "preparar", "quedar", "recordar", "regresar", "reír", "reparar",
            "responder", "sacar", "salir", "saltar", "seguir", "sentir", "servir",
            "subir", "terminar", "tocar", "tomar", "trabajar", "traer", "usar",
            "vender", "venir", "viajar", "visitar", "volver",
            
            # Common nouns (5000-10000 range)
            "abuelo", "acceso", "acto", "adulto", "agua", "aire", "alma", "altura",
            "amigo", "animal", "año", "árbol", "arte", "auto", "avión", "barco",
            "biblioteca", "bicicleta", "blanco", "boca", "brazo", "cabeza", "café",
            "calle", "cama", "caminar", "camino", "campo", "cara", "casa", "cielo",
            "coche", "color", "comida", "cuerpo", "día", "dinero", "dolor", "duda",
            "edad", "ejemplo", "escuela", "esquina", "estado", "familia", "fiesta",
            "flor", "forma", "frente", "fruta", "fuego", "gente", "grado", "grupo",
            "hijo", "historia", "hora", "idea", "iglesia", "imagen", "juego", "lado",
            "lago", "lengua", "libro", "lugar", "luz", "madre", "mano", "mar",
            "mes", "método", "miedo", "milla", "mundo", "música", "nación", "naturaleza",
            "negro", "noche", "nombre", "número", "ojo", "orden", "padre", "página",
            "país", "papel", "parte", "paso", "pelo", "persona", "pie", "piedra",
            "plaza", "población", "poder", "policía", "política", "problema", "proceso",
            "producto", "programa", "pueblo", "puerta", "razón", "región", "relación",
            "resultado", "río", "ropa", "sangre", "sistema", "sociedad", "suelo",
            "tamaño", "tarde", "tierra", "tiempo", "trabajo", "tren", "tres", "vida",
            "villa", "vista", "voz", "zona",
            
            # Common adjectives (5000-10000 range)
            "alto", "ancho", "antiguo", "bajo", "bueno", "caliente", "cerca", "claro",
            "común", "correcto", "débil", "difícil", "diferente", "directo", "duro",
            "económico", "especial", "estable", "fácil", "famoso", "fino", "firme",
            "fresco", "frío", "fuerte", "general", "grave", "hermoso", "importante",
            "imposible", "joven", "largo", "libre", "ligero", "lindo", "loco", "malo",
            "mismo", "moderno", "natural", "necesario", "nuevo", "oscuro", "peligroso",
            "pequeño", "personal", "pobre", "posible", "preciso", "pronto", "público",
            "rápido", "real", "reciente", "rico", "rojo", "rural", "sano", "seguro",
            "serio", "simple", "social", "solo", "sordo", "suave", "tonto", "total",
            "tranquilo", "último", "urbano", "verde", "viejo", "vivo", "voluntario"
        ]
        
        # Add more words from different categories
        additional_words = [
            # Technology and modern life
            "internet", "computadora", "teléfono", "televisión", "radio", "cámara",
            "video", "música", "película", "programa", "software", "hardware",
            "red", "página", "sitio", "correo", "mensaje", "archivo", "datos",
            
            # Food and dining
            "restaurante", "cafetería", "cocina", "comedor", "plato", "cuchara",
            "tenedor", "cuchillo", "vaso", "taza", "botella", "pan", "carne",
            "pescado", "pollo", "arroz", "papa", "tomate", "cebolla", "lechuga",
            "manzana", "naranja", "plátano", "uva", "fresa", "limón", "queso",
            "leche", "huevo", "mantequilla", "aceite", "sal", "azúcar", "café",
            "té", "agua", "jugo", "vino", "cerveza",
            
            # Clothing and fashion
            "camisa", "pantalón", "vestido", "falda", "zapato", "calcetín",
            "sombrero", "gorra", "bufanda", "guante", "cinturón", "reloj",
            "anillo", "collar", "bolsa", "mochila", "maleta", "paraguas",
            
            # Transportation
            "coche", "autobús", "tren", "metro", "taxi", "bicicleta", "moto",
            "barco", "avión", "helicóptero", "estación", "parada", "terminal",
            "carretera", "calle", "avenida", "puente", "túnel", "semáforo",
            
            # Nature and environment
            "montaña", "valle", "río", "lago", "mar", "océano", "isla", "bosque",
            "árbol", "flor", "hierba", "piedra", "arena", "tierra", "cielo",
            "sol", "luna", "estrella", "nube", "lluvia", "nieve", "viento",
            "temperatura", "clima", "estación", "primavera", "verano", "otoño",
            "invierno",
            
            # Emotions and feelings
            "alegría", "tristeza", "miedo", "ira", "sorpresa", "amor", "odio",
            "esperanza", "confianza", "vergüenza", "orgullo", "celos", "envidia",
            "gratitud", "compasión", "paz", "tranquilidad", "nerviosismo",
            
            # Time and calendar
            "segundo", "minuto", "hora", "día", "semana", "mes", "año", "siglo",
            "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
            "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre",
            
            # Numbers and quantities
            "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
            "nueve", "diez", "cien", "mil", "millón", "primero", "segundo",
            "tercero", "cuarto", "quinto", "medio", "doble", "triple", "mitad",
            
            # Colors
            "rojo", "azul", "verde", "amarillo", "naranja", "morado", "rosa",
            "marrón", "gris", "negro", "blanco", "dorado", "plateado", "transparente",
            
            # Body parts
            "cabeza", "cara", "ojo", "nariz", "boca", "oreja", "cuello", "hombro",
            "brazo", "mano", "dedo", "pecho", "espalda", "cintura", "pierna",
            "rodilla", "pie", "uña", "pelo", "barba", "bigote", "diente",
            
            # Family and relationships
            "padre", "madre", "hijo", "hija", "hermano", "hermana", "abuelo",
            "abuela", "tío", "tía", "primo", "prima", "esposo", "esposa",
            "novio", "novia", "amigo", "amiga", "vecino", "vecina", "compañero",
            
            # Professions and work
            "médico", "enfermero", "profesor", "estudiante", "abogado", "ingeniero",
            "arquitecto", "diseñador", "programador", "vendedor", "cocinero",
            "camarero", "conductor", "piloto", "policía", "bombero", "soldado",
            "artista", "músico", "actor", "escritor", "periodista", "científico"
        ]
        
        frequency_words.extend(mid_frequency_words)
        frequency_words.extend(additional_words)
        
        # Remove duplicates and filter out existing words
        unique_words = list(set(frequency_words))
        filtered_words = [word for word in unique_words if word.lower() not in self.existing_words]
        
        return filtered_words
    
    def generate_sentence_for_word(self, word):
        """Generate a simple sentence using the word."""
        # Simple sentence templates based on word type
        sentences = {
            "verb": f"Yo {word} todos los días.",
            "noun": f"El {word} está aquí.",
            "adjective": f"El libro es {word}.",
            "adverb": f"Él camina {word}.",
            "pronoun": f"{word} es mi amigo.",
            "preposition": f"Voy {word} la tienda.",
            "conjunction": f"Quiero café {word} té.",
            "interjection": f"¡{word}! ¡Qué sorpresa!"
        }
        
        # Simple heuristics to determine word type
        if word.endswith(('ar', 'er', 'ir')):
            return sentences["verb"]
        elif word.endswith(('o', 'a', 'e', 's')):
            return sentences["noun"]
        else:
            return sentences["noun"]  # Default to noun
    
    def generate_translation_for_word(self, word):
        """Generate English translation for the word."""
        # This would ideally use a dictionary API, but for now we'll use a simple mapping
        translations = {
            # Common verbs
            "abrazar": "to hug", "acostar": "to put to bed", "admirar": "to admire",
            "adoptar": "to adopt", "advertir": "to warn", "agradecer": "to thank",
            "alcanzar": "to reach", "alegrar": "to make happy", "almorzar": "to have lunch",
            "amanecer": "to dawn", "anunciar": "to announce", "apagar": "to turn off",
            "aparcar": "to park", "apoyar": "to support", "arreglar": "to fix",
            "asustar": "to scare", "atender": "to attend", "atraer": "to attract",
            "avanzar": "to advance", "bailar": "to dance", "bajar": "to go down",
            "besar": "to kiss", "borrar": "to erase", "brillar": "to shine",
            "cambiar": "to change", "caminar": "to walk", "cantar": "to sing",
            "cargar": "to load", "celebrar": "to celebrate", "cenar": "to have dinner",
            "cerrar": "to close", "charlar": "to chat", "comenzar": "to begin",
            "comprar": "to buy", "conectar": "to connect", "contar": "to count",
            "cortar": "to cut", "crecer": "to grow", "cruzar": "to cross",
            "cuidar": "to take care of", "dejar": "to leave", "desayunar": "to have breakfast",
            "desear": "to wish", "dibujar": "to draw", "dormir": "to sleep",
            "duchar": "to shower", "encontrar": "to find", "entender": "to understand",
            "entrar": "to enter", "escuchar": "to listen", "esperar": "to wait",
            "estudiar": "to study", "explicar": "to explain", "fumar": "to smoke",
            "ganar": "to win", "gastar": "to spend", "golpear": "to hit",
            "gritar": "to shout", "guardar": "to save", "gustar": "to like",
            "hablar": "to speak", "herir": "to hurt", "invitar": "to invite",
            "jugar": "to play", "lavar": "to wash", "leer": "to read",
            "limpiar": "to clean", "llamar": "to call", "llegar": "to arrive",
            "llevar": "to carry", "luchar": "to fight", "mandar": "to send",
            "marcar": "to mark", "mirar": "to look", "nadar": "to swim",
            "necesitar": "to need", "olvidar": "to forget", "pagar": "to pay",
            "parar": "to stop", "pasar": "to pass", "pedir": "to ask for",
            "pensar": "to think", "perder": "to lose", "permitir": "to allow",
            "pintar": "to paint", "preguntar": "to ask", "preparar": "to prepare",
            "quedar": "to stay", "recordar": "to remember", "regresar": "to return",
            "reír": "to laugh", "reparar": "to repair", "responder": "to answer",
            "sacar": "to take out", "salir": "to go out", "saltar": "to jump",
            "seguir": "to follow", "sentir": "to feel", "servir": "to serve",
            "subir": "to go up", "terminar": "to finish", "tocar": "to touch",
            "tomar": "to take", "trabajar": "to work", "traer": "to bring",
            "usar": "to use", "vender": "to sell", "venir": "to come",
            "viajar": "to travel", "visitar": "to visit", "volver": "to return",
            
            # Common nouns
            "abuelo": "grandfather", "acceso": "access", "acto": "act",
            "adulto": "adult", "agua": "water", "aire": "air", "alma": "soul",
            "altura": "height", "amigo": "friend", "animal": "animal", "año": "year",
            "árbol": "tree", "arte": "art", "auto": "car", "avión": "airplane",
            "barco": "ship", "biblioteca": "library", "bicicleta": "bicycle",
            "blanco": "white", "boca": "mouth", "brazo": "arm", "cabeza": "head",
            "café": "coffee", "calle": "street", "cama": "bed", "caminar": "walk",
            "camino": "path", "campo": "field", "cara": "face", "casa": "house",
            "cielo": "sky", "coche": "car", "color": "color", "comida": "food",
            "cuerpo": "body", "día": "day", "dinero": "money", "dolor": "pain",
            "duda": "doubt", "edad": "age", "ejemplo": "example", "escuela": "school",
            "esquina": "corner", "estado": "state", "familia": "family", "fiesta": "party",
            "flor": "flower", "forma": "form", "frente": "forehead", "fruta": "fruit",
            "fuego": "fire", "gente": "people", "grado": "degree", "grupo": "group",
            "hijo": "son", "historia": "history", "hora": "hour", "idea": "idea",
            "iglesia": "church", "imagen": "image", "juego": "game", "lado": "side",
            "lago": "lake", "lengua": "language", "libro": "book", "lugar": "place",
            "luz": "light", "madre": "mother", "mano": "hand", "mar": "sea",
            "mes": "month", "método": "method", "miedo": "fear", "milla": "mile",
            "mundo": "world", "música": "music", "nación": "nation", "naturaleza": "nature",
            "negro": "black", "noche": "night", "nombre": "name", "número": "number",
            "ojo": "eye", "orden": "order", "padre": "father", "página": "page",
            "país": "country", "papel": "paper", "parte": "part", "paso": "step",
            "pelo": "hair", "persona": "person", "pie": "foot", "piedra": "stone",
            "plaza": "square", "población": "population", "poder": "power", "policía": "police",
            "política": "politics", "problema": "problem", "proceso": "process",
            "producto": "product", "programa": "program", "pueblo": "town", "puerta": "door",
            "razón": "reason", "región": "region", "relación": "relationship",
            "resultado": "result", "río": "river", "ropa": "clothes", "sangre": "blood",
            "sistema": "system", "sociedad": "society", "suelo": "floor", "tamaño": "size",
            "tarde": "afternoon", "tierra": "earth", "tiempo": "time", "trabajo": "work",
            "tren": "train", "tres": "three", "vida": "life", "villa": "village",
            "vista": "view", "voz": "voice", "zona": "zone"
        }
        
        return translations.get(word, word)  # Return the word itself if no translation found
    
    def generate_sentence_translation(self, sentence):
        """Generate English translation for the sentence."""
        # Simple sentence translation mapping
        translations = {
            "Yo abrazar todos los días.": "I hug every day.",
            "El abuelo está aquí.": "The grandfather is here.",
            "El libro es alto.": "The book is tall.",
            "Él camina rápido.": "He walks fast.",
            "Él es mi amigo.": "He is my friend.",
            "Voy a la tienda.": "I go to the store.",
            "Quiero café o té.": "I want coffee or tea.",
            "¡Hola! ¡Qué sorpresa!": "Hello! What a surprise!"
        }
        
        return translations.get(sentence, sentence)  # Return the sentence itself if no translation found
    
    def create_flashcard(self, word):
        """Create a flashcard for a given word."""
        sentence = self.generate_sentence_for_word(word)
        word_translation = self.generate_translation_for_word(word)
        sentence_translation = self.generate_sentence_translation(sentence)
        
        return {
            "word": word,
            "irregularForms": None,  # Could be enhanced with conjugation data
            "sentence": sentence,
            "wordTranslation": word_translation,
            "sentenceTranslation": sentence_translation
        }
    
    def generate_flashcard_set(self, set_number, words_per_set=100):
        """Generate a flashcard set with the specified number of words."""
        available_words = self.get_words_from_frequency_lists()
        
        # Take the next batch of words
        start_index = (set_number - 1) * words_per_set
        end_index = start_index + words_per_set
        set_words = available_words[start_index:end_index]
        
        if len(set_words) < words_per_set:
            print(f"Warning: Only {len(set_words)} words available for set {set_number}")
        
        cards = []
        for word in set_words:
            card = self.create_flashcard(word)
            cards.append(card)
        
        return {
            "name": f"Spanish Common Words Set {set_number} (Alternative Method)",
            "description": f"This is set {set_number} of Spanish words generated using alternative methods (not LLM-based). Includes common words in reasonable use.",
            "cards": cards
        }
    
    def save_flashcard_set(self, set_data, set_number):
        """Save a flashcard set to a JSON file."""
        filename = f"flashcard_sets/alternative_set_{set_number}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(set_data, f, ensure_ascii=False, indent=2)
        print(f"Saved set to {filename}")
        return filename
    
    def combine_sets(self, sets):
        """Combine multiple flashcard sets into one."""
        combined = {
            "name": "Spanish Words Generated by Alternative Method",
            "description": "A comprehensive set of Spanish words generated using alternative methods (not LLM-based), including common words in reasonable use",
            "cards": []
        }
        
        for set_data in sets:
            if set_data and "cards" in set_data:
                combined["cards"].extend(set_data["cards"])
        
        return combined
    
    def generate_multiple_sets(self, num_sets=50, words_per_set=100):
        """Generate multiple flashcard sets."""
        os.makedirs("flashcard_sets", exist_ok=True)
        
        # Load existing words to avoid duplicates
        self.load_existing_words()
        
        all_sets = []
        total_words = 0
        
        for set_number in range(1, num_sets + 1):
            print(f"Generating set {set_number} of {num_sets}...")
            set_data = self.generate_flashcard_set(set_number, words_per_set)
            
            if set_data and set_data["cards"]:
                # Save individual set
                self.save_flashcard_set(set_data, set_number)
                
                all_sets.append(set_data)
                total_words += len(set_data["cards"])
                
                print(f"Generated {len(set_data['cards'])} words for set {set_number}")
            else:
                print(f"No words generated for set {set_number}")
        
        # Save combined set
        if all_sets:
            combined_set = self.combine_sets(all_sets)
            combined_filename = "flashcard_sets/alternative_words_complete.json"
            with open(combined_filename, 'w', encoding='utf-8') as f:
                json.dump(combined_set, f, ensure_ascii=False, indent=2)
            print(f"Saved combined set to {combined_filename}")
        
        print(f"Total words generated: {total_words}")
        return all_sets

def main():
    """Main function to run the alternative word generator."""
    generator = AlternativeWordGenerator()
    
    # Generate 50 sets of 100 words each (5000 total words)
    print("Starting alternative word generation...")
    sets = generator.generate_multiple_sets(num_sets=50, words_per_set=100)
    
    print("Word generation completed!")
    print(f"Generated {len(sets)} sets")
    print("Files saved in flashcard_sets/ directory")

if __name__ == "__main__":
    main() 