"""Strategy registry — maps language name to LanguageStrategy instance."""
from .base import LanguageStrategy
from .python import PythonStrategy

_REGISTRY: dict[str, LanguageStrategy] = {
    "python": PythonStrategy(),
}


def get_strategy(language: str) -> LanguageStrategy:
    lang = language.lower()
    if lang not in _REGISTRY:
        raise ValueError(f"No strategy registered for language '{language}'. "
                         f"Available: {sorted(_REGISTRY)}")
    return _REGISTRY[lang]
