"""Localization support for PC Parts Organizer."""

from __future__ import annotations

import json
from pathlib import Path

from pc_parts_organizer.models import CATEGORIES, COMPONENT_STATUSES
from pc_parts_organizer.storage import load_language_preference, save_language_preference

DEFAULT_LANGUAGE = "es"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("es", "en")
LANGUAGE_NAMES = {
    "es": "ES · Español",
    "en": "EN · English",
}


class LocalizationError(Exception):
    """Raised for localization or translation errors."""


class Translator:
    """Load translations and manage the active language."""

    def __init__(self) -> None:
        self._translations = self._load_all_translations()
        self._validate_translations()
        self._language = load_language_preference(SUPPORTED_LANGUAGES)

    @property
    def current_language(self) -> str:
        return self._language

    @property
    def language(self) -> str:
        return self._language

    def translate(self, key: str) -> str:
        data = self._translations[self._language]
        current: object = data
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                raise LocalizationError(f"Unknown translation key: {key}")
            current = current[part]
        if not isinstance(current, str):
            raise LocalizationError(f"Translation key is not a string: {key}")
        return current

    def t(self, key: str) -> str:
        return self.translate(key)

    def set_language(self, language: str) -> None:
        """Set the active language in memory after validation."""
        self._validate_language(language)
        self._language = language

    def change_language(self, language: str) -> None:
        """Persist the language first, then update the active language."""
        self._validate_language(language)
        save_language_preference(language, SUPPORTED_LANGUAGES)
        self._language = language

    def translate_category(self, canonical_category: str) -> str:
        categories = self._translations[self._language].get("categories", {})
        if canonical_category not in categories:
            raise LocalizationError(f"Unknown category key: {canonical_category}")
        return categories[canonical_category]

    def category_from_label(self, label: str) -> str:
        categories = self._translations[self._language].get("categories", {})
        for canonical, translated in categories.items():
            if translated == label:
                return canonical
        raise LocalizationError(f"Unknown localized category label: {label}")

    def translate_status(self, canonical_status: str) -> str:
        statuses = self._translations[self._language].get("component_statuses", {})
        if canonical_status not in statuses:
            raise LocalizationError(f"Unknown status key: {canonical_status}")
        return statuses[canonical_status]

    def status_from_label(self, label: str) -> str:
        statuses = self._translations[self._language].get("component_statuses", {})
        for canonical, translated in statuses.items():
            if translated == label:
                return canonical
        raise LocalizationError(f"Unknown localized status label: {label}")

    def get_language_options(self) -> list[tuple[str, str]]:
        return [(code, self._translations[code]["languages"][code]) for code in SUPPORTED_LANGUAGES]

    def _validate_language(self, language: str) -> None:
        if language not in SUPPORTED_LANGUAGES:
            raise LocalizationError(f"Unsupported language: {language}")

    def _locales_dir(self) -> Path:
        return Path(__file__).resolve().parent / "locales"

    def _load_all_translations(self) -> dict[str, dict[str, object]]:
        translations: dict[str, dict[str, object]] = {}
        for language in SUPPORTED_LANGUAGES:
            path = self._locales_dir() / f"{language}.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LocalizationError(f"Could not load translations for {language}.") from exc
            if not isinstance(data, dict):
                raise LocalizationError(f"Invalid translation resource for {language}.")
            translations[language] = data
        return translations

    def _collect_keys(self, data: object, prefix: str = "") -> set[str]:
        if not isinstance(data, dict):
            return {prefix} if prefix else set()
        keys: set[str] = set()
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                keys.update(self._collect_keys(value, full_key))
            else:
                keys.add(full_key)
        return keys

    def _get_value(self, data: dict[str, object], key: str) -> object:
        current: object = data
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def _validate_translations(self) -> None:
        base_keys = self._collect_keys(self._translations[SUPPORTED_LANGUAGES[0]])
        for language in SUPPORTED_LANGUAGES:
            keys = self._collect_keys(self._translations[language])
            if keys != base_keys:
                raise LocalizationError(f"Translation keys do not match for {language}.")
            for key in keys:
                value = self._get_value(self._translations[language], key)
                if key == "schema_version":
                    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                        raise LocalizationError(f"Translation value is empty or invalid: {language}:{key}")
                    continue
                if not isinstance(value, str) or not value.strip():
                    raise LocalizationError(f"Translation value is empty or invalid: {language}:{key}")
            categories = self._translations[language].get("categories")
            if not isinstance(categories, dict):
                raise LocalizationError(f"Missing categories for {language}.")
            if set(categories.keys()) != set(CATEGORIES):
                raise LocalizationError(f"Categories do not match canonical set for {language}.")
            for category in CATEGORIES:
                if not str(categories.get(category, "")).strip():
                    raise LocalizationError(f"Empty category translation for {language}:{category}")
            statuses = self._translations[language].get("component_statuses")
            if not isinstance(statuses, dict):
                raise LocalizationError(f"Missing component_statuses for {language}.")
            if set(statuses.keys()) != set(COMPONENT_STATUSES):
                raise LocalizationError(f"Component statuses do not match canonical set for {language}.")
            for status in COMPONENT_STATUSES:
                if not str(statuses.get(status, "")).strip():
                    raise LocalizationError(f"Empty component status translation for {language}:{status}")
            languages = self._translations[language].get("languages")
            if not isinstance(languages, dict):
                raise LocalizationError(f"Missing language names for {language}.")
            for supported in SUPPORTED_LANGUAGES:
                if not str(languages.get(supported, "")).strip():
                    raise LocalizationError(f"Missing language name {supported} in {language}.")