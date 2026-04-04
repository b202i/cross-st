# ai_error_handler.py — compatibility shim
# Source of truth: cross-ai-core package (cross_ai_core.ai_error_handler)
from cross_ai_core.ai_error_handler import *   # noqa: F401, F403
from cross_ai_core.ai_error_handler import (   # explicit for IDE / type checkers
    handle_api_error,
    is_quota_error,
    is_rate_limit_error,
    is_transient_error,
    get_error_type,
    retry_with_backoff,
    CrossAIError,
    QuotaExceededError,
    RateLimitError,
    TransientError,
)
