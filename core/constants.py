"""Shared application constants."""

# Default server connection
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

# UI defaults
WINDOW_WIDTH = 1360
WINDOW_HEIGHT = 860
# E11: floors for the window minimum. init_ui() raises these to the live
# minimumSizeHint when the content needs more (font/DPI dependent), so the
# window can never shrink into a state where controls overlap. The parameter
# panel scrolls (panel_scroll), which is what allows these to be far below the
# old 1100x700 minimum that the non-scrollable content actually required.
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 690
# E13: rounded-card window chrome. SHADOW_MARGIN is the transparent band
# around the card (room for the painted drop shadow); the card face is
# inset SHADOW_MARGIN from the window edge and the *content* is inset one
# more px (CARD_CONTENT_INSET) so the card's crisp 1px border always stays
# visible. When maximized the band collapses to 0 and the card fills the
# screen edge-to-edge. E13.1: the band is kept tight (10px) AND is the
# whole resize grip (main window passes CARD_CONTENT_INSET as the resize
# margin) — with the old 16px band + 6px grip the resize cursor sat in
# the fading shadow "outside" the visible card and was hard to reach;
# now it appears exactly at the visible card edge.
SHADOW_MARGIN = 10
CARD_RADIUS = 14
CARD_CONTENT_INSET = SHADOW_MARGIN + 1
TITLE_BAR_HEIGHT = 44
# A frameless window has no caption for the WM to keep on-screen, so the
# title-bar row can be dragged (or restored from a stale geometry) off the
# screen with nothing left to grab — _clamp_to_screen() keeps at least this
# many px of the top row visible.
TITLE_GRAB_MIN = 44
# E3 log window. Per level: each log level (D/I/W/E/F, plus the prefix-less
# group) keeps its own most-recent-N window, so a narrow filter view is never
# starved by a flood of hidden levels (a -lv 5 debug burst used to evict the
# few visible info lines out of the shared window, leaving a 1-line view).
# The unfiltered (all-on) view still uses one shared window of this size.
LOG_MAX_BLOCK_COUNT = 5000
# The visible document may hold one full window per visible level (5 levels
# incl. prefix-less and F) under a multi-level narrow filter.
LOG_DOC_MAX_BLOCK_COUNT = LOG_MAX_BLOCK_COUNT * 5
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
