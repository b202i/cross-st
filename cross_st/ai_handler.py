# ai_handler.py — compatibility shim
# Source of truth: cross-ai-core package (cross_ai_core.ai_handler)
# This file exists so st-*.py files and tests can continue to use:
#   from ai_handler import process_prompt, get_content, ...
from cross_ai_core.ai_handler import *        # noqa: F401, F403
from cross_ai_core.ai_handler import (        # explicit for IDE / type checkers
    AI_HANDLER_REGISTRY,
    AI_LIST,
    AIResponse,
    _API_KEY_ENV_VARS,                        # private — needed by tests
    check_api_key,
    get_ai_list,
    get_ai_make,
    get_ai_model,
    get_content,
    get_data_content,
    get_data_title,
    get_default_ai,
    get_usage,
    process_prompt,
    put_content,
)
