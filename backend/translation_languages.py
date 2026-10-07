"""Explicit output-language checks, never inferred from a text or its author."""
from collections.abc import Mapping
import re


def is_english_language(value):
    """Accept English ISO codes and BCP-47 tags; unknown is not English."""
    return isinstance(value, str) and bool(re.fullmatch(
        r'(?:en|eng)(?:-[a-z0-9]{2,8})*', value.strip().lower()))


def is_english_translation(record):
    """For translation projections, whose public shape may omit ``kind``."""
    return (isinstance(record, Mapping)
            and record.get('kind', 'translation') == 'translation'
            and is_english_language(record.get('language')))


def translation_allowed_in_search(record, language='', edition=''):
    """Non-English translations are source records only when explicitly selected."""
    return (record.get('kind') != 'translation' or is_english_translation(record)
            or bool(language and record.get('language') == language)
            or bool(edition and record.get('edition') == edition))
