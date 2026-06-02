from app.partner_redact import excerpt_markdown, redact_partner_text


def test_redact_partner_text_masks_email_and_phone():
    raw = "Contact owner@example.com or call 206-555-0100 at 123 Main Street Seattle WA"
    out = redact_partner_text(raw)
    assert "owner@example.com" not in out
    assert "206-555-0100" not in out
    assert "[email redacted]" in out
    assert "[phone redacted]" in out


def test_excerpt_markdown_truncates():
    long = "# Title\n\n" + ("paragraph.\n\n" * 50)
    out = excerpt_markdown(long, max_chars=200)
    assert len(out) < len(long)
    assert "excerpt" in out
