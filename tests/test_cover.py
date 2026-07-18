"""TC-09: cover letters — 400–1500 симв., без плейсхолдеров/HTML, 100% новых."""
from src import cover, store


def _rec(title="AI Product Manager"):
    r = store.new_record("100", "https://hh.ru/vacancy/100", title)
    r["company"] = "Acme AI"
    r["description"] = "Ищем лидера AI-направления для запуска LLM-продуктов."
    return r


def test_letter_ok_bounds():
    assert not cover.letter_ok("короткое")
    assert not cover.letter_ok("x" * 1501)
    good = "Здравствуйте!\n\n" + "Опыт запуска AI-продуктов и агентов. " * 12 + "\n\n" + cover.CLOSING
    assert cover.letter_ok(good)


def test_letter_ok_rejects_placeholders_and_html():
    base = "Здравствуйте!\n\n" + "Опыт запуска AI-продуктов и агентов. " * 12 + "\n\n"
    assert not cover.letter_ok(base + "{company_name} " + cover.CLOSING)
    assert not cover.letter_ok(base + "<b>жирный</b> " + cover.CLOSING)
    assert not cover.letter_ok(base + "[вставить кейс] " + cover.CLOSING)


def test_clean_letter_normalizes():
    raw = "Здравствуйте! Я **очень** хочу — работать.\n\n\n\nКейс: RAG."
    out = cover.clean_letter(raw)
    assert out.startswith("Здравствуйте!\n\n")
    assert "**" not in out and "—" not in out
    assert out.endswith(cover.CLOSING)


def test_fallback_when_ollama_unavailable(home):
    """Нет OLLAMA_API_KEY → детерминированный fallback, проходящий letter_ok."""
    rec = _rec()
    letter = cover.generate_for_record(rec)
    assert cover.letter_ok(letter), f"len={len(letter)}"
    assert rec["cover_letter"] == letter


def test_generate_all_covers_100pct(home):
    vac = {}
    for i in range(3):
        r = store.new_record(str(i), f"https://hh.ru/vacancy/{i}", f"AI Lead {i}")
        r["description"] = "AI трансформация процессов."
        vac[str(i)] = r
    n = cover.generate_all(vac, list(vac.keys()))
    assert n == 3
    assert all(vac[v]["cover_letter"] for v in vac)
