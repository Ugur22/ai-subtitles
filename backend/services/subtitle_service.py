"""
Subtitle generation service
"""
from typing import List, Dict
from utils.time_utils import format_srt_timestamp


class SubtitleService:
    """Service for subtitle generation"""

    @staticmethod
    def generate_srt(segments: List[Dict], use_translation: bool = False) -> str:
        """Generate SRT format subtitles from segments"""
        srt_content = []
        for i, segment in enumerate(segments, 1):
            try:
                # Convert timestamps to SRT format
                start_seconds = float(segment.get('start', 0.0))
                end_seconds = float(segment.get('end', 0.0))

                # Get text content, handling missing translation more gracefully
                text_content = None
                if use_translation:
                    # Use translation if available and not empty
                    text_content = segment.get('translation')
                    if not text_content or text_content.isspace():
                        print(f"Warning: Missing or empty translation for segment {i}, text: {segment.get('text', '[No Text]')}")
                        # Don't fall back to original text for missing translations
                        text_content = '[Translation Missing]'
                else:
                    # Use original text
                    text_content = segment.get('text')
                    if not text_content or text_content.isspace():
                        print(f"Warning: Missing or empty text for segment {i}")
                        text_content = '[No Text Available]'

                # Ensure text is properly encoded if it happens to be bytes
                if isinstance(text_content, bytes):
                    try:
                        text_content = text_content.decode('utf-8')
                    except UnicodeDecodeError:
                        print(f"Warning: Could not decode segment {i} text. Using placeholder.")
                        text_content = '[Encoding Error]'

                # Ensure text_content is a string before proceeding
                if not isinstance(text_content, str):
                    print(f"Warning: Segment {i} content is not a string ({type(text_content)}). Converting.")
                    text_content = str(text_content)

                # Format subtitle entry
                srt_content.extend([
                    str(i),
                    f"{format_srt_timestamp(start_seconds)} --> {format_srt_timestamp(end_seconds)}",
                    text_content.strip(),  # Ensure no leading/trailing whitespace
                    ""  # Empty line between entries
                ])
            except Exception as e:
                print(f"Error processing segment {i}: {str(e)}")
                # Add an error placeholder for this segment
                srt_content.extend([
                    str(i),
                    "00:00:00,000 --> 00:00:00,001",
                    f"[Error: Failed to process segment {i}]",
                    ""
                ])

        return "\n".join(srt_content)
