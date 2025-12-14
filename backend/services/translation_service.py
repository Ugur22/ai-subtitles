"""
Translation service using MarianMT models
"""
from typing import List, Dict, Tuple
from transformers import MarianMTModel, MarianTokenizer


class TranslationService:
    """Service for translating text using MarianMT models"""

    # Cache for loaded MarianMT models
    _marian_models: Dict[str, Tuple[MarianTokenizer, MarianMTModel]] = {}

    @classmethod
    def get_marian_model(cls, source_lang: str) -> Tuple[MarianTokenizer, MarianMTModel]:
        """Load MarianMT translation model for source_lang -> English.

        Args:
            source_lang: ISO language code (e.g., 'es', 'it', 'fr')

        Returns:
            Tuple of (tokenizer, model)

        Raises:
            Exception: If model doesn't exist for this language pair
        """
        model_name = f"Helsinki-NLP/opus-mt-{source_lang}-en"

        # Check if already loaded
        if model_name in cls._marian_models:
            print(f"[INFO] Using cached translation model: {model_name}")
            return cls._marian_models[model_name]

        # Try to load model with proper error handling
        try:
            print(f"[INFO] Loading translation model: {model_name}")
            tokenizer = MarianTokenizer.from_pretrained(model_name)
            model = MarianMTModel.from_pretrained(model_name)
            cls._marian_models[model_name] = (tokenizer, model)
            print(f"[SUCCESS] Model loaded: {model_name}")
            return cls._marian_models[model_name]

        except Exception as e:
            # Suggest alternatives if model doesn't exist
            available_alternatives = {
                'es': ['Helsinki-NLP/opus-mt-es-en'],
                'it': ['Helsinki-NLP/opus-mt-it-en'],
                'fr': ['Helsinki-NLP/opus-mt-fr-en'],
                'de': ['Helsinki-NLP/opus-mt-de-en'],
                'pt': ['Helsinki-NLP/opus-mt-pt-en'],
                'ru': ['Helsinki-NLP/opus-mt-ru-en'],
                'zh': ['Helsinki-NLP/opus-mt-zh-en'],
                'ja': ['Helsinki-NLP/opus-mt-ja-en'],
            }

            alt_models = available_alternatives.get(source_lang, [])
            error_msg = f"Translation model '{model_name}' not found. "

            if alt_models:
                error_msg += f"Alternatives: {', '.join(alt_models)}"
            else:
                error_msg += f"No translation model available for '{source_lang}' -> 'en'"

            print(f"[ERROR] {error_msg}")
            print(f"[ERROR] Original error: {str(e)}")
            raise Exception(error_msg)

    @classmethod
    def translate_segments(cls, segments: List[Dict], source_lang: str) -> List[Dict]:
        """Translate a batch of segments using local MarianMT model, preserving original text"""
        BATCH_SIZE = 10
        for i in range(0, len(segments), BATCH_SIZE):
            batch = segments[i:i + BATCH_SIZE]
            # Only translate segments with non-empty text
            batch_to_translate = [s for s in batch if s.get('text') and not s.get('text').isspace()]
            if not batch_to_translate:
                for segment in batch:
                    segment['translation'] = '[No speech detected]'
                continue

            try:
                # Use local translation model instead of OpenAI
                tokenizer, model = cls.get_marian_model(source_lang)

                # Translate each segment individually to preserve accuracy
                for segment in batch_to_translate:
                    text = segment.get('text', '').strip()
                    if not text:
                        segment['translation'] = '[No speech detected]'
                        continue

                    # Translate using MarianMT
                    inputs = tokenizer(text, return_tensors="pt", padding=True)
                    translated = model.generate(**inputs)
                    translation = tokenizer.decode(translated[0], skip_special_tokens=True)
                    segment['translation'] = translation.strip()

                print(f"Successfully translated {len(batch_to_translate)} segments using local model")
            except Exception as e:
                print(f"Error in translation process: {str(e)}")
                # If translation fails, set placeholder translations
                for segment in batch_to_translate:
                    segment['translation'] = f"[Translation pending for: {segment['text']}]"

        # Ensure all segments have a translation field
        for segment in segments:
            if not segment.get('translation'):
                segment['translation'] = '[No speech detected]'

        return segments
