from __future__ import annotations

from ocr_reconstructor.documents.markdown import parse_inline, parse_markdown


def test_parses_headings_with_levels():
    blocks = parse_markdown("# Title\n\n## Section\n\n### Sub\n")
    assert [b.kind for b in blocks] == ["heading", "heading", "heading"]
    assert [b.level for b in blocks] == [1, 2, 3]
    assert blocks[0].text == "Title"


def test_merges_soft_wrapped_paragraph_lines():
    blocks = parse_markdown("first line\nsecond line\n\nnew paragraph")
    assert [b.kind for b in blocks] == ["paragraph", "paragraph"]
    assert blocks[0].text == "first line second line"
    assert blocks[1].text == "new paragraph"


def test_lists_ordered_and_unordered():
    text = "- alpha\n- beta\n\n1. first\n2. second\n"
    blocks = [b for b in parse_markdown(text) if b.kind == "list_item"]
    assert [(b.ordered, b.text) for b in blocks[:2]] == [
        (False, "alpha"),
        (False, "beta"),
    ]
    assert [(b.ordered, b.number, b.text) for b in blocks[2:]] == [
        (True, "1", "first"),
        (True, "2", "second"),
    ]


def test_multiple_choice_options_stay_separate():
    text = "Soal.\n\n   A. pertama\n   B. kedua\n   C. ketiga\n"
    blocks = [b for b in parse_markdown(text) if b.kind == "list_item"]
    assert [(b.number, b.delimiter, b.text) for b in blocks] == [
        ("A", ".", "pertama"),
        ("B", ".", "kedua"),
        ("C", ".", "ketiga"),
    ]


def test_blockquote_and_rule():
    blocks = parse_markdown("> quoted text\n\n---\n")
    assert blocks[0].kind == "quote"
    assert blocks[0].text == "quoted text"
    assert blocks[1].kind == "rule"


def test_html_comments_are_ignored():
    blocks = parse_markdown("<!-- page: 001 · source: a.png -->\n\nbody")
    assert [b.kind for b in blocks] == ["paragraph"]
    assert blocks[0].text == "body"


def test_inline_bold_italic_code():
    spans = parse_inline("plain **bold** *ital* `code` end")
    flags = [(s.bold, s.italic, s.code) for s in spans]
    texts = [s.text for s in spans]
    assert "bold" in texts and "ital" in texts and "code" in texts
    assert (True, False, False) in flags
    assert (False, True, False) in flags
    assert (False, False, True) in flags
    assert (False, False, False) in flags
