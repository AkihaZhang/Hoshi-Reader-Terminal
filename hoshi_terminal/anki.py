from __future__ import annotations

from dataclasses import dataclass
from urllib import request
from urllib.error import URLError
import base64
import json
import re

from .audio import AudioAsset, mime_type_for_path


class AnkiConnectError(RuntimeError):
    pass


DEFAULT_LAPIS_FIELD_MAPPINGS = {
    "Expression": "{expression}",
    "ExpressionFurigana": "{furigana-plain}",
    "ExpressionReading": "{reading}",
    "ExpressionAudio": "{audio}",
    "SelectionText": "{popup-selection-text}",
    "MainDefinition": "{glossary-first}",
    "Sentence": "{sentence}",
    "SentenceAudio": "{sasayaki-audio}",
    "Picture": "{book-cover}",
    "Glossary": "{glossary}",
    "PitchPosition": "{pitch-accent-positions}",
    "PitchCategories": "{pitch-accent-categories}",
    "Frequency": "{frequencies}",
    "FreqSort": "{frequency-harmonic-rank}",
    "MiscInfo": "{document-title}",
    "IsWordAndSentenceCard": "x",
}
DEFAULT_LAPIS_FIELD_ORDER = list(DEFAULT_LAPIS_FIELD_MAPPINGS)


@dataclass(frozen=True)
class AnkiSettings:
    url: str
    deck: str
    model: str
    field_mappings: dict[str, str]
    tag: str
    mode: str
    allow_duplicates: bool = False
    duplicate_scope: str = "collection"
    check_duplicates_across_all_models: bool = False
    force_sync: bool = False


@dataclass(frozen=True)
class AnkiNoteType:
    name: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class MiningPayload:
    expression: str
    sentence: str = ""
    note: str = ""
    reading: str = ""
    matched: str = ""
    furigana_plain: str = ""
    glossary: str = ""
    glossary_first: str = ""
    frequencies: str = ""
    frequency_harmonic_rank: str = ""
    pitch_positions: str = ""
    pitch_categories: str = ""
    selection_text: str = ""
    document_title: str = ""
    book_cover: str = ""
    word_audio: AudioAsset | None = None
    sentence_audio_path: str = ""


def settings_from_dict(settings: dict[str, str]) -> AnkiSettings:
    field_mappings = _field_mappings_from_settings(settings)
    return AnkiSettings(
        url=settings.get("ankiconnect_url", "http://127.0.0.1:8765"),
        deck=settings.get("anki_deck", "Mining"),
        model=settings.get("anki_model", "Lapis"),
        field_mappings=field_mappings,
        tag=settings.get("anki_tag", "hoshi"),
        mode=settings.get("anki_mode", "both"),
        allow_duplicates=_bool_setting(settings.get("anki_allow_duplicates", "false")),
        duplicate_scope=_duplicate_scope(settings.get("anki_duplicate_scope", "collection")),
        check_duplicates_across_all_models=_bool_setting(settings.get("anki_check_all_models", "false")),
        force_sync=_bool_setting(settings.get("anki_force_sync", "false")),
    )


def add_note(
    settings: AnkiSettings,
    word: str,
    sentence: str = "",
    note: str = "",
    reading: str = "",
    glossary: str = "",
    glossary_first: str = "",
    word_audio: AudioAsset | None = None,
    sentence_audio_path: str = "",
    document_title: str = "",
    matched: str = "",
) -> int:
    payload = MiningPayload(
        expression=word,
        sentence=sentence,
        note=note,
        reading=reading,
        matched=matched or word,
        glossary=glossary,
        glossary_first=glossary_first,
        selection_text=word,
        document_title=document_title,
        word_audio=word_audio,
        sentence_audio_path=sentence_audio_path,
    )
    create_deck(settings)
    fields = render_fields(settings, payload)
    note_payload = {
        "deckName": settings.deck,
        "modelName": settings.model,
        "fields": fields,
        "tags": [settings.tag],
        "options": duplicate_options(settings),
    }
    result = invoke(settings.url, "addNote", {"note": note_payload})
    if not isinstance(result, int):
        raise AnkiConnectError(f"AnkiConnect 返回了异常 note id: {result!r}")
    if settings.force_sync:
        invoke(settings.url, "sync", {}, timeout=12.0)
    return result


def duplicate_options(settings: AnkiSettings) -> dict[str, object]:
    scope = _duplicate_scope(settings.duplicate_scope)
    options: dict[str, object] = {"allowDuplicate": settings.allow_duplicates}
    duplicate_scope_options: dict[str, object] = {}
    if scope == "deckroot":
        options["duplicateScope"] = "deck"
        duplicate_scope_options["deckName"] = settings.deck.split("::", 1)[0]
        duplicate_scope_options["checkChildren"] = True
    else:
        options["duplicateScope"] = scope
    if settings.check_duplicates_across_all_models:
        duplicate_scope_options["checkAllModels"] = True
    if duplicate_scope_options:
        options["duplicateScopeOptions"] = duplicate_scope_options
    return options


def is_duplicate(settings: AnkiSettings, expression: str, first_field: str | None = None) -> bool:
    key = expression.strip()
    if not key:
        return False
    field = first_field or next(iter(settings.field_mappings), "Expression")
    note_payload = {
        "deckName": settings.deck,
        "modelName": settings.model,
        "fields": {field: key},
        "options": duplicate_options(settings),
    }
    result = invoke(settings.url, "canAddNotesWithErrorDetail", {"notes": [note_payload]})
    if not isinstance(result, list) or not result:
        return False
    first = result[0]
    if not isinstance(first, dict):
        return False
    return not bool(first.get("canAdd", True))


def render_fields(settings: AnkiSettings, payload: MiningPayload, store_media: bool = True) -> dict[str, str]:
    word_audio_tag = ""
    if payload.word_audio is not None:
        word_audio_tag = _store_audio_asset(settings, payload.word_audio) if store_media else f"[sound:{payload.word_audio.filename}]"

    sentence_audio_tag = ""
    if payload.sentence_audio_path:
        sentence_audio_tag = (
            _store_media_path(settings, payload.sentence_audio_path)
            if store_media
            else f"[sound:{payload.sentence_audio_path.rsplit('/', 1)[-1]}]"
        )

    glossary_first = payload.glossary_first or payload.note
    glossary = payload.glossary or glossary_first
    values = {
        "{expression}": payload.expression,
        "{furigana-plain}": payload.furigana_plain,
        "{reading}": payload.reading,
        "{audio}": word_audio_tag,
        "{popup-selection-text}": payload.selection_text or payload.expression,
        "{glossary-first}": glossary_first,
        "{sentence}": bold_sentence(payload.sentence, payload.matched or payload.expression),
        "{sasayaki-audio}": sentence_audio_tag,
        "{book-cover}": payload.book_cover,
        "{glossary}": glossary,
        "{pitch-accent-positions}": payload.pitch_positions,
        "{pitch-accent-categories}": payload.pitch_categories,
        "{frequencies}": payload.frequencies,
        "{frequency-harmonic-rank}": payload.frequency_harmonic_rank,
        "{document-title}": payload.document_title,
    }
    fields: dict[str, str] = {}
    for field, template in settings.field_mappings.items():
        value = template
        for handlebar, replacement in values.items():
            value = value.replace(handlebar, replacement)
        if value:
            fields[field] = value
    return fields


def csv_fields(payload: MiningPayload) -> dict[str, str]:
    return render_fields(
        AnkiSettings(
            url="",
            deck="",
            model="Lapis",
            field_mappings=DEFAULT_LAPIS_FIELD_MAPPINGS,
            tag="hoshi",
            mode="csv",
        ),
        payload,
        store_media=False,
    )


def bold_sentence(sentence: str, matched: str) -> str:
    if not sentence:
        return ""
    if not matched:
        return sentence
    index = sentence.find(matched)
    if index < 0:
        return sentence
    return sentence[:index] + f"<b>{matched}</b>" + sentence[index + len(matched) :]


def create_deck(settings: AnkiSettings) -> None:
    invoke(settings.url, "createDeck", {"deck": settings.deck})


def version(url: str) -> int:
    result = invoke(url, "version", {})
    if not isinstance(result, int):
        raise AnkiConnectError(f"无法识别 AnkiConnect 版本: {result!r}")
    return result


def fetch_decks(url: str) -> list[str]:
    result = invoke(url, "deckNames", {}, timeout=5.0)
    if not isinstance(result, list):
        raise AnkiConnectError(f"无法识别 Anki 牌组列表: {result!r}")
    return [str(item) for item in result if str(item)]


def fetch_note_types(url: str) -> list[AnkiNoteType]:
    result = invoke(url, "modelNames", {}, timeout=5.0)
    if not isinstance(result, list):
        raise AnkiConnectError(f"无法识别 Anki 模板列表: {result!r}")
    note_types: list[AnkiNoteType] = []
    for model in [str(item) for item in result if str(item)]:
        fields = invoke(url, "modelFieldNames", {"modelName": model}, timeout=5.0)
        if not isinstance(fields, list):
            fields = []
        note_types.append(AnkiNoteType(model, tuple(str(field) for field in fields if str(field))))
    return note_types


def select_deck_after_fetch(decks: list[str], current: str) -> str:
    if current in decks:
        return current
    for deck in decks:
        if deck.lower() != "default":
            return deck
    return decks[0] if decks else current


def select_note_type_after_fetch(note_types: list[AnkiNoteType], current: str) -> AnkiNoteType | None:
    for note_type in note_types:
        if note_type.name == current:
            return note_type
    for note_type in note_types:
        if lapis_note_type_matches(note_type):
            return note_type
    return note_types[0] if note_types else None


def lapis_note_type_matches(note_type: AnkiNoteType) -> bool:
    fields = set(note_type.fields)
    return "lapis" in note_type.name.lower() or all(field in fields for field in ("Expression", "MainDefinition", "Sentence"))


def lapis_default_mappings_for_fields(fields: tuple[str, ...] | list[str]) -> dict[str, str]:
    return {field: DEFAULT_LAPIS_FIELD_MAPPINGS[field] for field in fields if field in DEFAULT_LAPIS_FIELD_MAPPINGS}


def invoke(url: str, action: str, params: dict[str, object], timeout: float = 1.5) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except URLError as exc:
        raise AnkiConnectError(f"连接 AnkiConnect 失败: {exc}") from exc
    except TimeoutError as exc:
        raise AnkiConnectError("连接 AnkiConnect 超时") from exc
    data = json.loads(raw)
    if data.get("error"):
        raise AnkiConnectError(str(data["error"]))
    return data.get("result")


def _field_mappings_from_settings(settings: dict[str, str]) -> dict[str, str]:
    raw = settings.get("anki_field_mappings", "")
    if raw:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            mappings = {str(key): str(value) for key, value in decoded.items() if str(value)}
            if mappings:
                return mappings
    if settings.get("anki_model", "Lapis").lower() == "basic":
        front = settings.get("anki_front_field", "Front")
        back = settings.get("anki_back_field", "Back")
        return {front: "{expression}", back: "{sentence}<br><br>{glossary-first}"}
    return dict(DEFAULT_LAPIS_FIELD_MAPPINGS)


def _bool_setting(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "开"}


def _duplicate_scope(value: str | None) -> str:
    normalized = str(value or "collection").strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "collection": "collection",
        "all": "collection",
        "deck": "deck",
        "deckroot": "deckroot",
        "root": "deckroot",
    }
    return aliases.get(normalized, "collection")


def _store_audio_asset(settings: AnkiSettings, asset: AudioAsset) -> str:
    return _store_media_bytes(settings, asset.filename, asset.data)


def _store_media_path(settings: AnkiSettings, path: str) -> str:
    with open(path, "rb") as handle:
        data = handle.read()
    filename = re.sub(r"[^0-9A-Za-z_.-]+", "_", path.rsplit("/", 1)[-1]).strip("_") or "hoshi_audio.mp3"
    return _store_media_bytes(settings, filename, data)


def _store_media_bytes(settings: AnkiSettings, filename: str, data: bytes) -> str:
    safe_name = re.sub(r"[^0-9A-Za-z_.-]+", "_", filename).strip("_") or "hoshi_audio.mp3"
    invoke(
        settings.url,
        "storeMediaFile",
        {
            "filename": safe_name,
            "data": base64.b64encode(data).decode("ascii"),
        },
        timeout=8.0,
    )
    return f"[sound:{safe_name}]" if mime_type_for_path(safe_name).startswith("audio/") else safe_name
