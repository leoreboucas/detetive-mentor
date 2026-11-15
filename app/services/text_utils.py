import unicodedata


def normalize(text):
    """Lowercase, strip accents and collapse whitespace."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")

    return " ".join(text.split())
