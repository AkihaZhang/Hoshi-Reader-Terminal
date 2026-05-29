from pathlib import Path
import tempfile
import time
import unittest

from hoshi_terminal.epub import Chapter, ExtractedBook
from hoshi_terminal.sasayaki import (
    SasayakiCue,
    SasayakiMatch,
    SasayakiMatchData,
    SasayakiPlayer,
    cue_at_or_before_time,
    ffplay_atempo_filter,
    find_cue_for_page,
    filter_sasayaki_text,
    format_time,
    match_rate_text,
    match_sasayaki,
    parse_srt,
    resolve_cue_audio_range,
)


class SasayakiTests(unittest.TestCase):
    def test_parse_srt_like_upstream(self) -> None:
        srt = (
            "1\r\n"
            "00:00:19,124 --> 00:00:22,016\r\n"
            "＊シックスイヤーザー号、\r\n\r\n"
            "2\r\n"
            "00:00:24,148 --> 00:00:28,468\r\n"
            "渚　それはある日の、あたし達にとっては日常の光景だった。\r\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test.srt"
            path.write_text(srt, encoding="utf-8")
            cues = parse_srt(path)

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].id, "0")
        self.assertAlmostEqual(cues[0].start_time, 19.124)
        self.assertAlmostEqual(cues[0].end_time, 22.016)
        self.assertEqual(cues[0].text, "＊シックスイヤーザー号、")
        self.assertEqual(cues[1].id, "1")

    def test_filter_removes_ruby_and_keeps_compatibility_ideographs(self) -> None:
        text = "<body><ruby>猪<rt>ちよ</rt>八<rt>はつ</rt>戒<rt>かい</rt></ruby>だ。</body>"
        self.assertEqual(filter_sasayaki_text(text), "猪八戒だ")

    def test_match_skips_short_star_cues_and_keeps_chapter_offsets(self) -> None:
        book = ExtractedBook(
            title="Book",
            chapters=[
                Chapter("one", "最初の文章です星次の本文です"),
                Chapter("two", "次の章の本文です。"),
            ],
        )
        cues = [
            SasayakiCue("0", 0.0, 1.0, "最初の文章です"),
            SasayakiCue("1", 1.0, 2.0, "＊星"),
            SasayakiCue("2", 2.0, 3.0, "次の本文です"),
            SasayakiCue("3", 3.0, 4.0, "次の章の本文です。"),
        ]

        match = match_sasayaki(book, cues, search_window=2)

        self.assertEqual([item.id for item in match.matches], ["0", "2", "3"])
        self.assertEqual(match.unmatched, 1)
        self.assertEqual(match.matches[2].chapter_index, 1)
        self.assertEqual(match.matches[2].start, 0)
        self.assertEqual(match_rate_text(match), "3/4 (75.0%)")

    def test_match_does_not_cross_chapter_boundaries(self) -> None:
        book = ExtractedBook(title="Book", chapters=[Chapter("a", "前半"), Chapter("b", "後半")])
        match = match_sasayaki(book, [SasayakiCue("0", 0.0, 1.0, "前半後半")], search_window=50)
        self.assertEqual(match.matches, [])
        self.assertEqual(match.unmatched, 1)

    def test_find_cue_for_page_ignores_tiny_cues(self) -> None:
        data = SasayakiMatchData(
            matches=[
                SasayakiMatch("short", 0.0, 0.2, "と", 0, 0, 1),
                SasayakiMatch("real", 1.0, 3.0, "覚えていたいよ", 0, 10, 7),
            ],
            unmatched=0,
        )

        cue = find_cue_for_page(data, "返事のない背中に向けて、続ける。「覚えていたいよ」と。")

        self.assertIsNotNone(cue)
        self.assertEqual(cue.id, "real")

    def test_format_time(self) -> None:
        self.assertEqual(format_time(3723.456), "01:02:03.456")

    def test_ffplay_atempo_filter_chains_out_of_range_speeds(self) -> None:
        self.assertEqual(ffplay_atempo_filter(1.0), "")
        self.assertEqual(ffplay_atempo_filter(2.5), "atempo=2.0,atempo=1.250")
        self.assertEqual(ffplay_atempo_filter(0.25), "atempo=0.5,atempo=0.500")

    def test_cue_at_or_before_time_keeps_navigation_anchor_after_cue_end(self) -> None:
        data = SasayakiMatchData(
            matches=[
                SasayakiMatch("a", 10.0, 11.0, "a", 0, 0, 1),
                SasayakiMatch("b", 20.0, 21.0, "b", 0, 2, 1),
            ],
            unmatched=0,
        )

        self.assertEqual(cue_at_or_before_time(data, 15.0).id, "a")

    def test_resolve_cue_audio_range_expands_adjacent_sentence_cues(self) -> None:
        target = SasayakiMatch("b", 12.0, 13.0, "は", 0, 1, 1)
        data = SasayakiMatchData(
            matches=[
                SasayakiMatch("a", 10.0, 12.0, "僕", 0, 0, 1),
                target,
                SasayakiMatch("c", 13.0, 15.5, "学校へ行った", 0, 2, 6),
                SasayakiMatch("d", 20.0, 21.0, "次の文", 0, 8, 3),
            ],
            unmatched=0,
        )

        self.assertEqual(resolve_cue_audio_range(data, target, "「僕は学校へ行った。」", delay=0.25), (10.25, 15.75))

    def test_player_current_time_falls_back_to_internal_clock(self) -> None:
        class FakeProcess:
            def poll(self) -> None:
                return None

        player = SasayakiPlayer()
        player.process = FakeProcess()  # type: ignore[assignment]
        player.player_name = "ffplay"
        player.base_position = 10.0
        player.rate = 1.0
        player.started_at = time.monotonic() - 2.0

        self.assertGreaterEqual(player.current_time() or 0.0, 11.5)


if __name__ == "__main__":
    unittest.main()
