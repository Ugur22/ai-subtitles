"""
Translation service using MarianMT models with optimized batch processing
"""
from typing import List, Dict, Tuple, Optional, Callable
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
    def translate_segments(
        cls,
        segments: List[Dict],
        source_lang: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[Dict]:
        """Translate segments using optimized batch processing.

        Args:
            segments: List of segment dictionaries with 'text' field
            source_lang: Source language code (e.g., 'es', 'it')
            progress_callback: Optional callback(translated_count, total_count) for progress updates

        Returns:
            Segments with 'translation' field populated
        """
        # Use larger batches for true batch processing (much faster than one-by-one)
        BATCH_SIZE = 32  # Optimal for MarianMT on CPU

        total_segments = len(segments)
        translated_count = 0

        print(f"[Translation] Starting batch translation of {total_segments} segments ({source_lang} -> en)")

        # Load model once before processing
        try:
            tokenizer, model = cls.get_marian_model(source_lang)
        except Exception as e:
            print(f"[Translation] Failed to load model: {e}")
            for segment in segments:
                segment['translation'] = None
            return segments

        for i in range(0, total_segments, BATCH_SIZE):
            batch = segments[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (total_segments + BATCH_SIZE - 1) // BATCH_SIZE

            # Collect texts to translate (filter empty)
            texts_to_translate = []
            segment_indices = []

            for idx, segment in enumerate(batch):
                text = segment.get('text', '').strip()
                if text:
                    texts_to_translate.append(text)
                    segment_indices.append(idx)
                else:
                    segment['translation'] = '[No speech detected]'

            if not texts_to_translate:
                translated_count += len(batch)
                if progress_callback:
                    progress_callback(translated_count, total_segments)
                continue

            try:
                # TRUE BATCH PROCESSING: tokenize and generate all at once
                inputs = tokenizer(
                    texts_to_translate,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=512
                )

                # Generate translations for entire batch at once
                translated_ids = model.generate(
                    **inputs,
                    max_length=512,
                    num_beams=4,
                    early_stopping=True
                )

                # Decode all translations
                translations = tokenizer.batch_decode(translated_ids, skip_special_tokens=True)

                # Assign translations back to segments
                for idx, translation in zip(segment_indices, translations):
                    batch[idx]['translation'] = translation.strip()

                translated_count += len(batch)

                # Log progress every batch
                print(f"[Translation] Batch {batch_num}/{total_batches}: translated {len(texts_to_translate)} segments ({translated_count}/{total_segments} total)")

                # Call progress callback
                if progress_callback:
                    progress_callback(translated_count, total_segments)

            except Exception as e:
                print(f"[Translation] Error in batch {batch_num}: {str(e)}")
                # Fall back to individual translation for this batch
                for idx in segment_indices:
                    text = batch[idx].get('text', '').strip()
                    try:
                        inputs = tokenizer(text, return_tensors="pt", padding=True)
                        translated = model.generate(**inputs)
                        translation = tokenizer.decode(translated[0], skip_special_tokens=True)
                        batch[idx]['translation'] = translation.strip()
                    except Exception as inner_e:
                        print(f"[Translation] Fallback failed for segment: {inner_e}")
                        batch[idx]['translation'] = None

                translated_count += len(batch)
                if progress_callback:
                    progress_callback(translated_count, total_segments)

        # Ensure all segments have translation field
        for segment in segments:
            if 'translation' not in segment:
                segment['translation'] = '[No speech detected]'

        print(f"[Translation] Completed: {translated_count}/{total_segments} segments translated")
        return segments
