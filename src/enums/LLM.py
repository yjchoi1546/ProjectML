from enum import StrEnum


class LLM(StrEnum):
    GPT4_1 = "gpt-4.1-2025-04-14"
    GPT4_1_MINI = "gpt-4.1-mini-2025-04-14"
    GPT4_1_NANO = "gpt-4.1-nano-2025-04-14"
    GPT4O = "gpt-4o-2024-08-06"
    GPT5_1 = "gpt-5.1-2025-11-13"
    GPT5_MINI = "gpt-5-mini"
    GPT5_NANO = "gpt-5-nano-2025-08-07"
    GPT5_2_INTANT = "gpt-5.2-instant"

    # Claude (Anthropic)
    CLAUDE_3_5_SONNET = "claude-3-5-sonnet-20241022"
    CLAUDE_3_5_HAIKU = "claude-3-5-haiku-20241022"
    CLAUDE_3_OPUS = "claude-3-opus-20240229"
    CLAUDE_3_SONNET = "claude-3-sonnet-20240229"
    CLAUDE_3_HAIKU = "claude-3-haiku-20240307"

    # Gemini (Google AI Studio - API Key 방식)
    GEMINI_2_5_PRO = "google-genai:gemini-2.5-pro"
    GEMINI_2_5_FLASH = "google-genai:gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE = "google-genai:gemini-2.5-flash-lite"
    GEMINI_3_PRO_PREVIEW = "google-genai:gemini-3-pro-preview"

    # Grok (xAI)
    # Grok 3 계열
    GROK_3_BETA = "grok-3-beta"
    GROK_3_MINI_BETA = "grok-3-mini-beta"

    # Grok 4 계열 (현 시점 최고 성능 모델군)
    GROK_4_1_FAST_REASONING = "grok-4-1-fast-reasoning"
    GROK_4_1_FAST_NON_REASONING = "grok-4-1-fast-non-reasoning"
    GROK_4_FAST_REASONING = "grok-4-fast-reasoning"
    GROK_4_FAST_NON_REASONING = "grok-4-fast-non-reasoning"
    GROK_4 = "grok-4"

    LLAMA_3_3_70B_VERSATILE = "llama-3.3-70b-versatile"
    LLAMA_3_1_8B_INSTANT = "llama-3.1-8b-instant"
    OPENAI_GPT_OSS_20B = "openai/gpt-oss-20b"
    
    KIMI_K2_INSTRUCT_0905 = "moonshotai/kimi-k2-instruct-0905"
