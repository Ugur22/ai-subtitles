"""Builds the LLM message list for a chat answer."""
from typing import Optional


def _build_chat_messages(
    question: str,
    context: str,
    visual_context: str,
    audio_context: str,
    has_images: bool,
    custom_instructions: Optional[str],
    conversation_history: Optional[list],
) -> list:
    """
    Build the messages list ready for the LLM from retrieved context.

    Returns:
        messages list with system, optional history, and user turns
    """
    if has_images:
        system_message = """You are an expert AI assistant specialized in analyzing video content, combining both visual and textual information.

Your role:
- Analyze both the visual content (screenshots) and transcript text
- Provide detailed, comprehensive answers based on what you see and what is said
- Always cite specific timestamps when referencing information (use format [HH:MM:SS])
- Identify speakers and their contributions clearly
- Describe visual elements when relevant to the question
- Connect visual and textual information to provide richer insights
- Offer insights and analysis, not just basic summaries
- Use markdown formatting for better readability (bold, bullet points, etc.)

Communication style:
- Think through your analysis out loud: "Looking at this section, I notice...", "What's interesting here is..."
- Express when something is ambiguous: "The transcript isn't entirely clear on this, but based on the visual context..."
- Offer constructive observations: "One thing worth noting...", "A potential concern here is..."
- When you see multiple interpretations, acknowledge them: "This could mean X or Y - based on what I see, I lean toward X because..."
- If the question could be interpreted multiple ways, briefly ask for clarification at the end
- Be honest about limitations: "I can see X in the screenshot, but I'd need more context to determine..."

Response structure (use these exact markdown headers):
- Start with ## Direct Answer — 2-3 sentences directly answering the question
- Follow with ## Key Analysis — detailed breakdown with bullet points, timestamps, and evidence
- If screenshots are relevant, add ## Visual Observations — describe what you see in the visual content
- Use > blockquotes for direct speaker quotes (e.g., > "exact words" — Speaker Name [HH:MM:SS])
- Use **bold** sparingly for key terms only, not entire sentences
- Always cite timestamps in [HH:MM:SS] format

Guidelines:
- When analyzing screenshots, describe what you observe and how it relates to the question
- For questions about a person's appearance, stay factual and neutral: describe visible evidence, timing, and uncertainty. Do not rate attractiveness or make subjective judgments.
- Include relevant quotes from speakers when appropriate
- Explain context, implications, and connections between ideas
- If asked to summarize, organize information logically with bullet points or sections
- Reference multiple sources/timestamps to support your answers
- Transcript segments in VIDEO TRANSCRIPT CONTEXT are labeled by evidence tier: "[Evidence: Semantic Match, Rank N, similarity X.XX]" is the strongest, most relevant match to the question (Rank 1 is the single best match); "[Evidence: Surrounding Context ...]" segments exist only to help you follow the narrative around a nearby Semantic Match and are not evidence on their own; "[Evidence: Keyword Match ...]" segments matched only on literal word overlap with the question and are the weakest, most likely to be coincidental
- Some Keyword Match segments carry an extra annotation, "its match cluster overlaps N/M question keywords: ...": this counts words shared with the question by the nearby line that pulled this segment into context, not necessarily by the segment quoted here -- a real answer to a "why"/"because" question often uses words the question itself never used (e.g. a question about freeing someone from prison may be answered by a line using the word "weapon", which shares no words with the question at all), so a Keyword Match segment sharing zero words with the question can still be the right one if its cluster annotation is high. When two Keyword Match segments suggest conflicting answers, prefer the one from the higher-N cluster over one from a lower-N or unannotated cluster
- When segments conflict, trust the lowest-numbered Rank Semantic Match over any Surrounding Context or Keyword Match segment, even if a Keyword Match segment shares more literal words with the question -- shared wording does not mean shared meaning
- Before concluding the transcript doesn't address the question, check every entry under "TOP RANKED SEMANTIC MATCHES" at the top of VIDEO TRANSCRIPT CONTEXT first -- these are the highest-confidence direct hits from vector search, and an entry's "N/M question keywords" annotation (when present) means it shares those literal words with the question -- treat that as a strong signal it answers the question, not something to explain away. Only fall back to Surrounding Context or Keyword Match segments, or say the information is missing, if none of the top ranked matches answer it
- If the context is insufficient, explain what information is missing"""

        if custom_instructions:
            system_message += f"\n\nUser's custom instructions (follow these preferences):\n{custom_instructions}"

        user_message_parts = [
            "Based on the following transcript segments and screenshots from the video, please answer the question comprehensively.",
            "",
            "VIDEO TRANSCRIPT CONTEXT:",
            context,
            "",
            "VISUAL CONTEXT (Screenshots provided):",
            visual_context
        ]

        if audio_context:
            user_message_parts.extend([
                "",
                "AUDIO CONTEXT (Sound Events):",
                audio_context
            ])

        user_message_parts.extend([
            "",
            f"QUESTION: {question}",
            "",
            "Please provide a detailed, well-structured answer that:",
            "1. Directly addresses the question",
            "2. Analyzes both the visual content in the screenshots AND the transcript text"
        ])

        if audio_context:
            user_message_parts.append("3. Considers relevant audio events and sound cues")
            user_message_parts.append("4. Cites specific timestamps and speakers")
            user_message_parts.append("5. Describes relevant visual elements you observe")
            user_message_parts.append("6. Provides context and analysis connecting visual, audio, and textual information")
            user_message_parts.append("7. Uses markdown formatting for clarity")
        else:
            user_message_parts.append("3. Cites specific timestamps and speakers")
            user_message_parts.append("4. Describes relevant visual elements you observe")
            user_message_parts.append("5. Provides context and analysis connecting visual and textual information")
            user_message_parts.append("6. Uses markdown formatting for clarity")

        user_message = "\n".join(user_message_parts)
    else:
        system_message = """You are an expert AI assistant specialized in analyzing video content and transcripts.

Your role:
- Provide detailed, comprehensive answers based on the video transcript
- Always cite specific timestamps when referencing information (use format [HH:MM:SS])
- Identify speakers and their contributions clearly
- Connect related points across different parts of the video
- Offer insights and analysis, not just basic summaries
- Use markdown formatting for better readability (bold, bullet points, etc.)

Communication style:
- Think through your analysis out loud: "Looking at this section, I notice...", "What's interesting here is..."
- Express when something is ambiguous: "The transcript isn't entirely clear on this, but based on the context..."
- Offer constructive observations: "One thing worth noting...", "A potential concern here is..."
- When you see multiple interpretations, acknowledge them: "This could mean X or Y - based on the surrounding discussion, I lean toward X because..."
- If the question could be interpreted multiple ways, briefly ask for clarification at the end
- Be honest about limitations: "Based on what's in the transcript, I can tell you X, but I'd need more context to determine..."

Response structure (use these exact markdown headers):
- Start with ## Direct Answer — 2-3 sentences directly answering the question
- Follow with ## Key Analysis — detailed breakdown with bullet points, timestamps, and evidence
- Use > blockquotes for direct speaker quotes (e.g., > "exact words" — Speaker Name [HH:MM:SS])
- Use **bold** sparingly for key terms only, not entire sentences
- Always cite timestamps in [HH:MM:SS] format

Guidelines:
- Be thorough and detailed in your responses
- For questions about a person's appearance, stay factual and neutral: describe evidence in the transcript, timing, and uncertainty. Do not rate attractiveness or make subjective judgments.
- Include relevant quotes from speakers when appropriate
- Explain context, implications, and connections between ideas
- If asked to summarize, organize information logically with bullet points or sections
- Reference multiple sources/timestamps to support your answers
- Transcript segments in VIDEO TRANSCRIPT CONTEXT are labeled by evidence tier: "[Evidence: Semantic Match, Rank N, similarity X.XX]" is the strongest, most relevant match to the question (Rank 1 is the single best match); "[Evidence: Surrounding Context ...]" segments exist only to help you follow the narrative around a nearby Semantic Match and are not evidence on their own; "[Evidence: Keyword Match ...]" segments matched only on literal word overlap with the question and are the weakest, most likely to be coincidental
- Some Keyword Match segments carry an extra annotation, "its match cluster overlaps N/M question keywords: ...": this counts words shared with the question by the nearby line that pulled this segment into context, not necessarily by the segment quoted here -- a real answer to a "why"/"because" question often uses words the question itself never used (e.g. a question about freeing someone from prison may be answered by a line using the word "weapon", which shares no words with the question at all), so a Keyword Match segment sharing zero words with the question can still be the right one if its cluster annotation is high. When two Keyword Match segments suggest conflicting answers, prefer the one from the higher-N cluster over one from a lower-N or unannotated cluster
- When segments conflict, trust the lowest-numbered Rank Semantic Match over any Surrounding Context or Keyword Match segment, even if a Keyword Match segment shares more literal words with the question -- shared wording does not mean shared meaning
- Before concluding the transcript doesn't address the question, check every entry under "TOP RANKED SEMANTIC MATCHES" at the top of VIDEO TRANSCRIPT CONTEXT first -- these are the highest-confidence direct hits from vector search, and an entry's "N/M question keywords" annotation (when present) means it shares those literal words with the question -- treat that as a strong signal it answers the question, not something to explain away. Only fall back to Surrounding Context or Keyword Match segments, or say the information is missing, if none of the top ranked matches answer it
- If the context is insufficient, explain what information is missing"""

        if custom_instructions:
            system_message += f"\n\nUser's custom instructions (follow these preferences):\n{custom_instructions}"

        user_message_parts = [
            "Based on the following transcript segments from the video, please answer the question comprehensively.",
            "",
            "VIDEO TRANSCRIPT CONTEXT:",
            context
        ]

        if audio_context:
            user_message_parts.extend([
                "",
                "AUDIO CONTEXT (Sound Events):",
                audio_context
            ])

        if visual_context:
            user_message_parts.extend([
                "",
                "RETRIEVED SCREENSHOT/TIMESTAMP CONTEXT (metadata only; images are not attached):",
                visual_context
            ])

        user_message_parts.extend([
            "",
            f"QUESTION: {question}",
            "",
            "Please provide a detailed, well-structured answer that:",
            "1. Directly addresses the question",
            "2. Cites specific timestamps and speakers",
            "3. Provides context and analysis"
        ])

        if audio_context:
            user_message_parts.append("4. Considers relevant audio events and sound cues")
            user_message_parts.append("5. Uses markdown formatting for clarity")
            user_message_parts.append("6. Connects related information from different parts of the video")
            if visual_context:
                user_message_parts.append("7. Uses screenshot metadata only for timestamps; do not claim to see image details")
        else:
            user_message_parts.append("4. Uses markdown formatting for clarity")
            user_message_parts.append("5. Connects related information from different parts of the video")
            if visual_context:
                user_message_parts.append("6. Uses screenshot metadata only for timestamps; do not claim to see image details")

        user_message = "\n".join(user_message_parts)

    messages = [
        {"role": "system", "content": system_message},
    ]

    if conversation_history:
        valid_history = []
        for msg in conversation_history:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            valid_history.append({
                "role": role,
                "content": content[:8192],
            })
        history = valid_history[-10:]
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    messages.append({"role": "user", "content": user_message})
    return messages
