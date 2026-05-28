from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import time

from .epub import Chapter, ExtractedBook


@dataclass(frozen=True)
class SasayakiCue:
    id: str
    start_time: float
    end_time: float
    text: str


@dataclass(frozen=True)
class SasayakiMatch:
    id: str
    start_time: float
    end_time: float
    text: str
    chapter_index: int
    start: int
    length: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "text": self.text,
            "chapterIndex": self.chapter_index,
            "start": self.start,
            "length": self.length,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SasayakiMatch":
        return cls(
            id=str(data["id"]),
            start_time=float(data["startTime"]),
            end_time=float(data["endTime"]),
            text=str(data["text"]),
            chapter_index=int(data["chapterIndex"]),
            start=int(data["start"]),
            length=int(data["length"]),
        )


@dataclass(frozen=True)
class SasayakiMatchData:
    matches: list[SasayakiMatch]
    unmatched: int

    def to_dict(self) -> dict[str, object]:
        return {"matches": [match.to_dict() for match in self.matches], "unmatched": self.unmatched}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SasayakiMatchData":
        raw_matches = data.get("matches", [])
        matches = [SasayakiMatch.from_dict(item) for item in raw_matches if isinstance(item, dict)]
        return cls(matches=matches, unmatched=int(data.get("unmatched", 0)))


@dataclass(frozen=True)
class ChapterRange:
    chapter_index: int
    start: int
    length: int

    @property
    def end(self) -> int:
        return self.start + self.length


FILTER_RE = re.compile(
    r"[^0-9A-Za-z○◯々-〇〻ぁ-ゖゝ-ゞァ-ヺー０-９Ａ-Ｚａ-ｚｦ-ﾝ"
    r"\u2E80-\u2FDF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]"
)
TIMESTAMP_RE = re.compile(r"^\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")


def parse_srt(path: str | Path) -> list[SasayakiCue]:
    data = Path(path).expanduser().read_bytes()
    return parse_srt_bytes(data)


def parse_srt_bytes(data: bytes) -> list[SasayakiCue]:
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    cues: list[SasayakiCue] = []
    for index, block in enumerate(text.split("\n\n")):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        match = TIMESTAMP_RE.match(lines[1])
        if not match:
            continue
        cues.append(
            SasayakiCue(
                id=str(index),
                start_time=parse_timestamp(match.group(1)),
                end_time=parse_timestamp(match.group(2)),
                text=lines[2].strip(),
            )
        )
    return cues


def parse_timestamp(timestamp: str) -> float:
    parts = timestamp.strip().replace(",", ".").split(":")
    if len(parts) != 3:
        raise ValueError(f"无效 SRT 时间戳：{timestamp}")
    return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])


def filter_sasayaki_text(text: str) -> str:
    body = re.search(r"(?is)<body.*?</body>", text)
    if body:
        text = body.group(0)
    text = re.sub(r"(?is)<rt[^>]*>.*?</rt>", "", text)
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text.replace("&nbsp;", " "))
    return FILTER_RE.sub("", text)


def match_sasayaki(extracted: ExtractedBook, cues: list[SasayakiCue], search_window: int = 200) -> SasayakiMatchData:
    return match_sasayaki_chapters(extracted.chapters, cues, search_window=search_window)


def match_sasayaki_chapters(chapters: list[Chapter], cues: list[SasayakiCue], search_window: int = 200) -> SasayakiMatchData:
    source_parts: list[str] = []
    ranges: list[ChapterRange] = []
    for index, chapter in enumerate(chapters):
        text = filter_sasayaki_text(chapter.text)
        ranges.append(ChapterRange(chapter_index=index, start=sum(len(part) for part in source_parts), length=len(text)))
        source_parts.append(text)
    source = "".join(source_parts)

    start = 0
    min_start: int | None = None
    for cue in cues[:15]:
        if cue.text.startswith("＊"):
            continue
        text = filter_sasayaki_text(cue.text)
        if len(text) < 6:
            continue
        index = source.find(text)
        if index >= 0:
            min_start = min(index, min_start) if min_start is not None else index
    if min_start is not None:
        start = min_start

    matches: list[SasayakiMatch] = []
    unmatched = 0
    cursor = start
    for cue in cues:
        text = filter_sasayaki_text(cue.text)
        if not text:
            unmatched += 1
            continue
        if cue.text.startswith("＊") and len(text) < 5:
            unmatched += 1
            continue
        search_end = min(len(source), cursor + len(text) + max(0, search_window))
        index = source.find(text, cursor, search_end)
        if index < 0:
            unmatched += 1
            continue
        end = index + len(text)
        chapter_range = next((item for item in ranges if index >= item.start and index < item.end), None)
        if chapter_range is None or end > chapter_range.end:
            unmatched += 1
            continue
        cursor = end
        matches.append(
            SasayakiMatch(
                id=cue.id,
                start_time=cue.start_time,
                end_time=cue.end_time,
                text=cue.text,
                chapter_index=chapter_range.chapter_index,
                start=index - chapter_range.start,
                length=len(text),
            )
        )
    return SasayakiMatchData(matches=matches, unmatched=unmatched)


def match_rate(data: SasayakiMatchData) -> tuple[int, int, float]:
    matched = len(data.matches)
    total = matched + data.unmatched
    percentage = matched / total * 100.0 if total else 0.0
    return matched, total, percentage


def match_rate_text(data: SasayakiMatchData) -> str:
    matched, total, percentage = match_rate(data)
    return f"{matched}/{total} ({percentage:.1f}%)"


def find_cue_for_page(data: SasayakiMatchData, page_text: str) -> SasayakiMatch | None:
    filtered_page = filter_sasayaki_text(page_text)
    if not filtered_page:
        return None
    candidates: list[tuple[int, int, SasayakiMatch]] = []
    for cue in data.matches:
        cue_text = filter_sasayaki_text(cue.text)
        if len(cue_text) < 4:
            continue
        position = filtered_page.find(cue_text)
        if position >= 0:
            candidates.append((position, -len(cue_text), cue))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def cue_at_time(data: SasayakiMatchData, seconds: float) -> SasayakiMatch | None:
    for cue in data.matches:
        if cue.start_time <= seconds <= cue.end_time:
            return cue
    return None


def next_cue(data: SasayakiMatchData, after: float) -> SasayakiMatch | None:
    for cue in data.matches:
        if cue.start_time > after + 0.01:
            return cue
    return None


def previous_cue(data: SasayakiMatchData, before: float) -> SasayakiMatch | None:
    previous: SasayakiMatch | None = None
    for cue in data.matches:
        if cue.start_time >= before - 0.01:
            break
        previous = cue
    return previous


def format_time(seconds: float) -> str:
    whole = int(max(0, seconds))
    millis = int(round((max(0.0, seconds) - whole) * 1000))
    hours, remainder = divmod(whole, 3600)
    minutes, sec = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}.{millis:03d}"


class SasayakiPlayer:
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None

    def play(
        self,
        audio_path: str | Path,
        start_time: float = 0.0,
        rate: float = 1.0,
        duration: float | None = None,
    ) -> tuple[list[str], str]:
        self.stop()
        command, player = audio_command(audio_path, start_time=start_time, rate=rate, duration=duration)
        self.process = _open_audio_process(command, player)
        return command, player

    def stop(self, timeout: float = 0.3) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        deadline = time.monotonic() + timeout
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.03)
        if process.poll() is None:
            process.kill()


def audio_command(
    audio_path: str | Path,
    start_time: float = 0.0,
    rate: float = 1.0,
    duration: float | None = None,
) -> tuple[list[str], str]:
    path = str(Path(audio_path).expanduser())
    start = max(0.0, start_time)
    speed = max(0.1, rate)
    length = max(0.05, duration) if duration is not None else None
    if shutil.which("mpv"):
        command = ["mpv", "--no-video", "--force-window=no", "--really-quiet", f"--start={start:.3f}", f"--speed={speed:.3f}"]
        if length is not None:
            command.append(f"--length={length:.3f}")
        command.append(path)
        return command, "mpv"
    if shutil.which("ffplay"):
        command = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "-ss", f"{start:.3f}"]
        if length is not None:
            command.extend(["-t", f"{length:.3f}"])
        filter_chain = ffplay_atempo_filter(speed)
        if filter_chain:
            command.extend(["-af", filter_chain])
        command.append(path)
        return command, "ffplay"
    system = platform.system()
    if system == "Darwin":
        return ["open", path], "open"
    if system == "Windows":
        return ["cmd", "/c", "start", "", path], "start"
    if shutil.which("xdg-open"):
        return ["xdg-open", path], "xdg-open"
    raise RuntimeError("没有找到可用音频播放器。建议安装 mpv 或 ffplay。")


def launch_audio(
    audio_path: str | Path,
    start_time: float = 0.0,
    rate: float = 1.0,
    duration: float | None = None,
) -> tuple[list[str], str]:
    command, player = audio_command(audio_path, start_time=start_time, rate=rate, duration=duration)
    _open_audio_process(command, player)
    return command, player


def ffplay_atempo_filter(rate: float) -> str:
    speed = max(0.1, rate)
    filters: list[str] = []
    while speed > 2.0:
        filters.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        filters.append("atempo=0.5")
        speed /= 0.5
    if abs(speed - 1.0) > 0.01:
        filters.append(f"atempo={speed:.3f}")
    return ",".join(filters)


def _open_audio_process(command: list[str], player: str) -> subprocess.Popen[bytes] | None:
    if player in {"open", "start", "xdg-open"}:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
        return None
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
