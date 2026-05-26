from __future__ import annotations

from dataclasses import dataclass
from urllib import request
from urllib.error import URLError
import json


class AnkiConnectError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnkiSettings:
    url: str
    deck: str
    model: str
    front_field: str
    back_field: str
    tag: str
    mode: str


def settings_from_dict(settings: dict[str, str]) -> AnkiSettings:
    return AnkiSettings(
        url=settings.get("ankiconnect_url", "http://127.0.0.1:8765"),
        deck=settings.get("anki_deck", "Hoshi Reader Terminal"),
        model=settings.get("anki_model", "Basic"),
        front_field=settings.get("anki_front_field", "Front"),
        back_field=settings.get("anki_back_field", "Back"),
        tag=settings.get("anki_tag", "hoshi-terminal"),
        mode=settings.get("anki_mode", "both"),
    )


def add_note(settings: AnkiSettings, word: str, sentence: str = "", note: str = "") -> int:
    create_deck(settings)
    back = sentence or note or "Hoshi Reader Terminal mined this card."
    if note and sentence:
        back = f"{sentence}<br><br>{note}"
    payload = {
        "deckName": settings.deck,
        "modelName": settings.model,
        "fields": {
            settings.front_field: word,
            settings.back_field: back,
        },
        "tags": [settings.tag],
        "options": {
            "allowDuplicate": False,
            "duplicateScope": "deck",
        },
    }
    result = invoke(settings.url, "addNote", {"note": payload})
    if not isinstance(result, int):
        raise AnkiConnectError(f"AnkiConnect 返回了异常 note id: {result!r}")
    return result


def create_deck(settings: AnkiSettings) -> None:
    invoke(settings.url, "createDeck", {"deck": settings.deck})


def version(url: str) -> int:
    result = invoke(url, "version", {})
    if not isinstance(result, int):
        raise AnkiConnectError(f"无法识别 AnkiConnect 版本: {result!r}")
    return result


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
