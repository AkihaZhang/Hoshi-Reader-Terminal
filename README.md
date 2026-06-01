# Hoshi Reader Terminal ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey) ![Install](https://img.shields.io/badge/install-one--click%20script-3fb6e8) ![License](https://img.shields.io/badge/license-MIT-blue)

**English** | [简体中文](README.zh-CN.md)

Hoshi Reader Terminal is a cross-platform terminal reader for Japanese books. It provides a bookshelf, paginated reading, Yomitan dictionary lookup, Anki card creation, Sasayaki audiobook matching, reading statistics, and local TTU-style progress sync.

It follows the structure of Hoshi Reader iOS and Android where terminal interaction makes sense.

<p align="center">
  <img src="docs/images/01-menu.svg" alt="Main menu" width="760">
</p>

| Reader | Dictionary |
| --- | --- |
| <img src="docs/images/02-reader.svg" alt="Reader screenshot"> | <img src="docs/images/03-dictionary.svg" alt="Dictionary screenshot"> |

| Sync | Settings |
| --- | --- |
| <img src="docs/images/04-sync.svg" alt="Sync screenshot"> | <img src="docs/images/05-settings.svg" alt="Settings screenshot"> |

| Sasayaki |
| --- |
| <img src="docs/images/06-sasayaki.svg" alt="Sasayaki screenshot"> |

## Features

- Bookshelf-first reading: import books, open books from the shelf, rename/delete books, mark books as read, sync one book, or start Sasayaki matching from the book context.
- Supports `.epub`, `.txt`, `.md`, `.html`, and `.xhtml`.
- Terminal reader with arrow-key page turns, lookup, card creation, highlights, notes, statistics, horizontal layout, and terminal vertical layout.
- Yomitan Term / Frequency / Pitch dictionary import from zip files or folders.
- Dictionary priority controls, enable/disable toggles, paginated lookup results, recursive lookup, and color-coded terminal badges.
- Sasayaki flow for SubPlz `.srt` matching, local or online audio, cue navigation, cue highlighting, playback position, delay, and speed.
- CSV card export and AnkiConnect card creation with Hoshi/Lapis-style default fields.
- Word audio from online sources or an Ankiconnect Android `android.db` local audio database.
- Local progress/statistics sync using a `ttu-reader-data` style folder.
- Simplified Chinese, English, and Japanese interface labels.
- GitHub Release update checks and in-place portable updates.

## Install

Use the one-click script for your OS:

```bash
# macOS / Linux
curl -fsSL https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest/download/install.sh | sh
```

```powershell
# Windows PowerShell
irm https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest/download/install.ps1 | iex
```

Then run:

```bash
hoshi
```

Portable packages are available from [GitHub Releases](https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/tag/v0.1.14):

| OS | Package |
| --- | --- |
| Windows | `Hoshi-Reader-Terminal-0.1.14-windows.zip` |
| macOS | `Hoshi-Reader-Terminal-0.1.14-macos.tar.gz` |
| Linux | `Hoshi-Reader-Terminal-0.1.14-linux.tar.gz` |

Python 3.10+ is required.

## Common Commands

```text
hoshi                         Open the terminal menu
hoshi import PATH             Import a book
hoshi shelf                   Show the shelf; enter a number to read
hoshi read TARGET             Read by number, id, title fragment, or path
hoshi lookup WORD             Look up a word
hoshi dict-import PATH        Import a Yomitan dictionary
hoshi dict-list [TYPE]        List Term / Frequency / Pitch dictionaries
hoshi dict-order TYPE FROM TO Reorder dictionaries
hoshi card WORD               Create a CSV/AnkiConnect card
hoshi sync [auto|export|import]
hoshi sasayaki status BOOK
hoshi sasayaki match BOOK SRT --audio AUDIO
hoshi settings
hoshi update --check
hoshi update -y
```

Chinese aliases such as `菜单`, `导入`, `书架`, `阅读`, `查词`, `导入词典`, `制卡`, `统计`, `同步`, `有声书`, `设置`, `诊断`, `检查更新`, and `更新` are also supported.

## Data Directory

- Windows: `%APPDATA%\HoshiReaderTerminal`
- macOS: `~/Library/Application Support/HoshiReaderTerminal`
- Linux: `~/.local/share/hoshi-reader-terminal`

## License

MIT License. See [LICENSE](LICENSE).
