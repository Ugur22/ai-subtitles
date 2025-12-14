"""
Text summarization service using BART model
"""
from typing import Optional, Tuple
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM


class SummarizationService:
    """Service for text summarization using BART"""

    # Global model cache (singleton pattern)
    _tokenizer: Optional[AutoTokenizer] = None
    _model: Optional[AutoModelForSeq2SeqLM] = None
    _model_name: str = "facebook/bart-large-cnn"

    @classmethod
    def get_summarization_model(cls) -> Tuple[Optional[AutoTokenizer], Optional[AutoModelForSeq2SeqLM]]:
        """Get or initialize the summarization model"""
        try:
            # Try to load the model from cache first
            tokenizer = AutoTokenizer.from_pretrained(cls._model_name)
            model = AutoModelForSeq2SeqLM.from_pretrained(cls._model_name)
            return tokenizer, model
        except Exception as e:
            print(f"Error loading summarization model: {str(e)}")
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
