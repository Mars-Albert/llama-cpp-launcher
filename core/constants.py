"""Shared application constants."""

# Default server connection
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

# UI defaults
WINDOW_WIDTH = 1360
WINDOW_HEIGHT = 860
MIN_WINDOW_WIDTH = 1100
MIN_WINDOW_HEIGHT = 700
LOG_MAX_BLOCK_COUNT = 5000
UNDO_HISTORY_MAX = 20
PREVIEW_TIMER_MS = 300
UNDO_DEBOUNCE_MS = 800
VERSION_CHECK_TIMEOUT_S = 10

# GGUF Inspector
# B6: each GGUFInfo can hold a 150k-token list plus multi-MB tokenizer JSON
# strings; 10 entries pinned the worst case into hundreds of MB. 3 is enough
# to cover the usual model/mmproj re-inspection cycle.
PARSE_CACHE_MAX = 3

# Context size quick-pick buttons
CONTEXT_SIZE_PRESETS = [4096, 8192, 16384, 32768, 65536, 131072, 262144]

# Main GPU range
MAIN_GPU_MAX = 15
