# Hoshi Reader Terminal ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey) ![Install](https://img.shields.io/badge/install-one--click%20script-3fb6e8) ![License](https://img.shields.io/badge/license-GPLv3-blue)

**English** | [简体中文](README.zh-CN.md)

Hoshi Reader Terminal is a cross-platform terminal reader for Japanese books. It provides a bookshelf, paginated reading, Yomitan dictionary lookup, Anki card creation, Sasayaki audiobook matching, reading statistics, and Google Drive based ッツ/TTU sync.

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

- Bookshelf-first reading: import books, open books from the shelf, use custom shelves, unshelved and reading sections, and sort by recent access or title.
- Book context actions for rename/delete, mark-as-read, moving between shelves, one-book sync, and Sasayaki matching.
- Supports `.epub`, `.txt`, `.md`, `.html`, and `.xhtml`.
- Terminal reader with arrow-key page turns, table-of-contents jumps, in-book search, lookup, card creation, highlights, notes, highlight-list jumps, statistics, horizontal layout, and terminal vertical layout.
- Yomitan Term / Frequency / Pitch dictionary import from zip files or folders.
- Dictionary priority controls, enable/disable toggles, paginated lookup results, recursive lookup, and color-coded terminal badges.
- Sasayaki flow for SubPlz `.srt` matching, local or online audio, cue navigation, cue highlighting, playback position, delay, and speed.
- CSV card export and AnkiConnect card creation with Hoshi/Lapis-style default fields.
- Word audio from online sources or an Ankiconnect Android `android.db` local audio database.
- Google Drive `ttu-reader-data` sync for reading progress, statistics, Sasayaki playback position, and book data. A local-folder backend remains available for compatibility and debugging.
- Simplified Chinese and English interface labels.
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

All systems use the same `hoshi-terminal.pyz` from the [latest GitHub Release](https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest). The two installers only handle the different shell and PATH conventions.

Python 3.10+ is required; the release asset is a cross-platform Python application archive, not a bundled Python runtime.

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
hoshi sync connect            Connect Google Drive
hoshi sync status             Show connection status
hoshi sync [auto|export|import]
hoshi sync books              List the remote TTU library
hoshi sync get --book BOOK    Import a book from bookdata
hoshi sync local --path PATH  Use the local compatibility backend
hoshi sasayaki status BOOK
hoshi sasayaki match BOOK SRT --audio AUDIO
hoshi settings
hoshi update --check
hoshi update -y
```

Chinese aliases such as `菜单`, `导入`, `书架`, `阅读`, `查词`, `导入词典`, `制卡`, `统计`, `同步`, `有声书`, `设置`, `诊断`, `检查更新`, and `更新` are also supported.

## Google Drive / ッツ Sync

1. Enable the Google Drive API in a Google Cloud project and add the `https://www.googleapis.com/auth/drive.file` scope.
2. Create an OAuth client of type **TVs and Limited Input devices**.
3. Run `hoshi sync connect` and enter the Client ID and Client Secret.
4. Google opens a device authorization page; enter the code printed in the terminal.
5. Run `hoshi sync auto`, or use Settings -> Advanced -> Sync.

OAuth credentials are stored in `google_drive_auth.json` inside the application data directory. The file uses mode `0600` on macOS/Linux and is excluded from Hoshi Reader Terminal backups.

## Data Directory

- Windows: `%APPDATA%\HoshiReaderTerminal`
- macOS: `~/Library/Application Support/HoshiReaderTerminal`
- Linux: `~/.local/share/hoshi-reader-terminal`

## License

Distributed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for details.
