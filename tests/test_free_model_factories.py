# import os  # unused import removed
from pathlib import Path

def test_model_present_in_free_model_factories():
    file_path = Path('.github/free-model-factories.tsv')
    content = file_path.read_text()
    assert 'ollama-cloud' in content
    assert 'nemotron-3-nano:30b' in content