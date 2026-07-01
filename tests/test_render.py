"""Tests for the !progress table's width-aware column fitting (SPEC §6)."""

from __future__ import annotations

from procrastination_terminator.bot import _disp_width, _fit

# Fullwidth punctuation, escaped so the source stays free of ASCII-lookalike glyphs:
# U+FF08/FF09 fullwidth parens, U+FF1A fullwidth colon.
_FW_LPAREN, _FW_RPAREN, _FW_COLON = chr(0xFF08), chr(0xFF09), chr(0xFF1A)


def test_disp_width_counts_cjk_as_two() -> None:
    assert _disp_width("abc") == 3
    assert _disp_width("睡觉") == 4  # two wide glyphs
    assert _disp_width("Game睡") == 6  # 4 narrow + 1 wide


def test_fit_pads_ascii_to_display_width() -> None:
    assert _fit("todo", 7) == "todo   "


def test_fit_truncates_ascii_with_marker() -> None:
    assert _fit("Game Chapter", 8) == "Game Ch~"


def test_fit_pads_cjk_by_display_width() -> None:
    # "睡觉" is 4 columns wide, so a width-6 cell needs two trailing spaces.
    assert _fit("睡觉", 6) == "睡觉  "
    assert _disp_width(_fit("睡觉", 6)) == 6


def test_fit_truncates_cjk_without_overflowing_the_cell() -> None:
    fitted = _fit("起床早餐老婆饼", 6)  # 14 columns of CJK into a 6-column cell
    assert _disp_width(fitted) == 6  # cell stays exactly 6 columns wide
    assert "~" in fitted  # and it is marked as truncated


def test_fit_handles_a_wide_glyph_that_cannot_fit() -> None:
    # A single wide glyph into a width-1 cell degrades to just the truncation mark.
    assert _fit("睡", 1) == "~"


def test_fit_folds_fullwidth_punctuation_to_ascii() -> None:
    # Fullwidth parens render narrower than a full CJK cell in many fonts, breaking
    # alignment; NFKC folds them to ASCII so every cell is a reliable width.
    fitted = _fit(f"晚饭{_FW_LPAREN}三文鱼{_FW_RPAREN}", 20)
    assert _FW_LPAREN not in fitted and "(" in fitted
    assert _FW_RPAREN not in fitted and ")" in fitted
    assert _disp_width(fitted) == 20


def test_fit_truncation_leaves_no_space_before_the_mark() -> None:
    # The trailing space where the cut lands is stripped so the mark hugs the text,
    # and the fullwidth paren/colon in the input fold to ASCII.
    text = f"起床{_FW_LPAREN}早餐{_FW_COLON}老婆饼 吃药{_FW_RPAREN}"
    assert _fit(text, 18) == "起床(早餐:老婆饼~ "
