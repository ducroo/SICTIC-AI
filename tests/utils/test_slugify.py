import pytest
from lib.slugify import slugify

def test_slugify_basic():
    """Test basic slugification of simple strings."""
    assert slugify("Hello World") == "hello-world"
    assert slugify("Some_String") == "some-string"
    assert slugify("  Extra   Spaces  ") == "extra-spaces"

def test_slugify_accents():
    """Test that accents and umlauts are correctly decomposed to ascii."""
    assert slugify("Agnès Petit Markowski") == "agnes-petit-markowski"
    assert slugify("Bernhard Trösch") == "bernhard-trosch"
    assert slugify("Jörg Sabel") == "jorg-sabel"
    assert slugify("René Müller") == "rene-muller"

def test_slugify_special_chars():
    """Test handling of special characters and emojis."""
    assert slugify("Startup: The Future") == "startup-the-future"
    assert slugify("Qwen3.5:9b") == "qwen3-5-9b"
    assert slugify("Hello 🌍 World") == "hello-world"
    assert slugify("multi---hyphen") == "multi-hyphen"

def test_slugify_empty():
    """Test handling of empty or None inputs."""
    assert slugify("") == ""
    assert slugify(None) == ""
