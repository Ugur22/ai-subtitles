"""
Text summarization service using BART model
"""
import os
from typing import Optional, Tuple
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM


class SummarizationService:
    """Service for text summarization using BART"""

    # Global model cache (singleton pattern)
    _tokenizer: Optional[AutoTokenizer] = None
    _model: Optional[AutoModelForSeq2SeqLM] = None
    _model_name: str = "facebook/bart-large-cnn"
    _model_load_attempted: bool = False
    _model_load_error: Optional[str] = None

    @classmethod
    def get_summarization_model(cls) -> Tuple[Optional[AutoTokenizer], Optional[AutoModelForSeq2SeqLM]]:
        """Get or initialize the summarization model"""
        # If we already tried and failed, don't retry repeatedly
        if cls._model_load_attempted and cls._model_load_error:
            print(f"Skipping model load - previous error: {cls._model_load_error}")
            return None, None

        cls._model_load_attempted = True

        try:
            # Try to load from local cache first (prevents network requests)
            cache_dir = os.environ.get('HF_HOME', '/app/.cache/huggingface')
            print(f"Loading summarization model {cls._model_name} (cache: {cache_dir})")

            try:
                tokenizer = AutoTokenizer.from_pretrained(cls._model_name, local_files_only=True)
                model = AutoModelForSeq2SeqLM.from_pretrained(cls._model_name, local_files_only=True)
                print(f"Loaded {cls._model_name} from local cache successfully")
                return tokenizer, model
            except Exception as cache_error:
                print(f"Model not in local cache: {cache_error}")

            # Fall back to downloading (may be rate limited without HF_TOKEN)
            hf_token = os.environ.get('HUGGINGFACE_TOKEN') or os.environ.get('HF_TOKEN')
            if not hf_token:
                print("WARNING: HF_TOKEN not set - may be rate limited when downloading model")

            tokenizer = AutoTokenizer.from_pretrained(cls._model_name, token=hf_token)
            model = AutoModelForSeq2SeqLM.from_pretrained(cls._model_name, token=hf_token)
            print(f"Downloaded and loaded {cls._model_name} successfully")
            return tokenizer, model

        except Exception as e:
            error_msg = str(e)
            cls._model_load_error = error_msg

            # Provide specific guidance for rate limiting errors
            if "rate limit" in error_msg.lower() or "429" in error_msg:
                print(f"ERROR: HuggingFace rate limit hit loading {cls._model_name}. "
                      "Set HF_TOKEN environment variable or pre-download the model in Docker build.")
            else:
                print(f"Error loading summarization model: {error_msg}")

            return None, None

    @classmethod
    def generate_local_summary(cls, text: str, max_length: int = 150, min_length: int = 50) -> str:
        """Generate a summary using the local model"""

        # Initialize the model if not already done
        if cls._tokenizer is None or cls._model is None:
            cls._tokenizer, cls._model = cls.get_summarization_model()
            if cls._tokenizer is None or cls._model is None:
                return "Summary generation failed: Model could not be loaded."

        try:
            # Tokenize the input text
            inputs = cls._tokenizer(text, return_tensors="pt", max_length=1024, truncation=True)

            # Generate summary
            summary_ids = cls._model.generate(
                inputs["input_ids"],
                max_length=max_length,
                min_length=min_length,
                length_penalty=2.0,
                num_beams=4,
                early_stopping=True
            )

            # Decode the summary
            summary = cls._tokenizer.decode(summary_ids[0], skip_special_tokens=True)
            return summary
        except Exception as e:
            print(f"Error generating summary: {str(e)}")
            return f"Summary generation failed: {str(e)}"
