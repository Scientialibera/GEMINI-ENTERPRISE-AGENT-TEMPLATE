"""Shared palette and layout measurements: geometry in inches, type in points."""

PAGE_W = 10.0
PAGE_H = 13.33
LEFT_W = 3.45
GAP = 0.28
RIGHT_X = LEFT_W + GAP
RIGHT_W = PAGE_W - RIGHT_X - 0.22
# The hero meets the blue panel and reaches the top and right page edges.
HERO_X = LEFT_W
HERO_W = PAGE_W - LEFT_W
HERO_H = 7.42
C = {
    "blue": "6F97C5",
    "dark_blue": "07347A",
    "yellow": "F9B800",
    "yellow2": "FFC515",
    "ink": "1D2530",
    "muted": "5C6573",
    "pale": "F5F1E6",
    "line": "0D3D85",
    "white": "FFFFFF",
    "cream": "FBF8F0",
    "grey": "E8E8E8",
    "border": "D8D8D8",
}
HEAD_FONT = "Georgia"
BODY_FONT = "Aptos"
# Conservative mean character widths and line heights for fixed-size text.
CHAR_WIDTH_RATIO = 0.45
HEAD_CHAR_WIDTH_RATIO = 0.41
LINE_HEIGHT_RATIO = 1.22
POINTS_PER_INCH = 72.0

TITLE_FONT_SIZE = 36.0
TITLE_FONT_SIZE_LONG = 28.0
TITLE_LONG_THRESHOLD = 28
TIP_CHARS_PER_LINE = 92
TIP_LINE_HEIGHT = 0.26
TIP_VERTICAL_PADDING = 0.30
INGREDIENT_FONT_SIZE = 10.0
INGREDIENT_ROW_MAX_HEIGHT = 0.72
# Keep rows readable; additional ingredients go onto continuation pages.
INGREDIENT_ROW_MIN_HEIGHT = 0.46
INGREDIENT_PANEL_PADDING = 0.22
INGREDIENT_MAX_ROWS = 12
INGREDIENT_PANEL_TOP = 4.45
INGREDIENT_PANEL_MAX_BOTTOM = 12.42
STEP_IMAGE_WIDTH_FRACTION = 0.46
STEP_IMAGE_MIN_ASPECT = 1.05
CHEF_NOTE_FONT_SIZE = 11.5
VARIATIONS_GAP = 0.30
VARIATIONS_MIN_TOP = 8.30
VARIATIONS_MAX_TOP = 10.30
VARIATIONS_MIN_TOP_SHORT_PAGE = 6.40
VARIATIONS_TO_BANNER = 1.84
STEP_BLOCK_GAP = 0.24
STEP_BLOCK_MIN_HEIGHT = 2.60
# Bound expansion so photographs do not dominate short instruction pages.
STEP_BLOCK_MAX_SCALE = 1.85
STEP_BLOCK_COLUMN_SHARE = 0.58
STEPS_PAGE_BOTTOM = 12.60
STEPS_LAST_PAGE_BOTTOM = 8.90
STEP_TITLE_FONT_SIZE = 20.0
STEP_TITLE_BOX_HEIGHT = 0.62
BULLET_FONT_SIZE = 10.0
BULLET_LINE_HEIGHT = 0.56
WORDS_PER_BULLET_LINE = 6
BULLET_ROW_PADDING = 0.10
