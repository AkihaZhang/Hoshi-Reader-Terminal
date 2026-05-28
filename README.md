# Hoshi Reader Terminal ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey) ![Install](https://img.shields.io/badge/install-one--click%20script-3fb6e8) ![License](https://img.shields.io/badge/license-MIT-blue)

**English** | [简体中文](README.zh-CN.md)

A terminal Japanese EPUB reader inspired by [Hoshi Reader iOS](https://github.com/Manhhao/Hoshi-Reader) and [Hoshi Reader Android](https://github.com/HuangAntimony/Hoshi-Reader-Android), with bookshelf management, Yomitan lookup, Anki card creation, reading statistics, and local progress sync.

Hoshi Reader Terminal is for true cyber ascetics: it puts novel reading, dictionary lookup, and card creation entirely inside the terminal, thoroughly fixing the design flaw that Hoshi Reader is too easy to use.

<p align="center">
  <img src="docs/images/01-menu.svg" alt="Main menu" width="760">
</p>

| Reader | Dictionary |
| --- | --- |
| <img src="docs/images/02-reader.svg" alt="Reader screenshot"> | <img src="docs/images/03-dictionary.svg" alt="Dictionary screenshot"> |

| Sync | Settings |
| --- | --- |
| <img src="docs/images/04-sync.svg" alt="Sync screenshot"> | <img src="docs/images/05-settings.svg" alt="Settings screenshot"> |

## Features

### Bookshelf

- Import one or multiple `.epub`, `.txt`, `.md`, `.html`, or `.xhtml` books.
- Open books by numeric shelf selection, title fragment, id, or file path.
- Keep reading progress, reading statistics, highlights, and notes.
- Configure the default book directory from the terminal menu.

### Reading

- Read in paginated terminal pages.
- Switch between horizontal text and a simple terminal vertical layout.
- Use clear reader commands with examples shown on screen:
  - `/読みました` for lookup
  - `a 読む` for card creation
  - `h note` for highlight notes

### Lookup

- Import Yomitan Term / Frequency / Pitch dictionaries from folders or zip files.
- Enable, disable, and reorder dictionaries inside each type.
- Search from the Dictionary menu, the command line, or inside the reader.
- Page through long lookup results with arrow keys, and run recursive `/word` lookups inside the result view.
- Includes lightweight Japanese deinflection for common polite and past forms.

### Anki Cards

- Write card rows to CSV.
- Send cards through AnkiConnect when available.
- Configure deck, model, fields, tags, and AnkiConnect URL from Settings.

### Sync And Backup

- Export and import progress/statistics through a local `ttu-reader-data` style sync folder.
- Create backups outside the data directory so the backup archive never includes itself.

### Interface

- Launch the terminal menu with `hoshi`.
- Switch interface labels between Simplified Chinese, English, and Japanese.
- Uses a neofetch-style terminal logo based on the Hoshi icon.
- Check GitHub Releases for updates from the terminal.

## Download

Download portable packages from [GitHub Releases](https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/tag/v0.1.6). The one-click scripts below are the recommended install path. Portable zip/tar packages require Python 3.10+.

| OS | Package |
| --- | --- |
| Windows | `Hoshi-Reader-Terminal-0.1.6-windows.zip` |
| macOS | `Hoshi-Reader-Terminal-0.1.6-macos.tar.gz` |
| Linux | `Hoshi-Reader-Terminal-0.1.6-linux.tar.gz` |

After installation, run:

```bash
hoshi
```

## One-Click Install

```bash
# macOS / Linux
curl -fsSL https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest/download/install.sh | sh
```

```powershell
# Windows PowerShell
irm https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest/download/install.ps1 | iex
```

The script downloads the latest release package for your OS and installs the `hoshi` command. Python 3.10+ is required; if Python is missing, the script prints what to do next.

## Commands

```text
menu                         Open main menu
import PATH                  Import a book
shelf                        Show bookshelf
read TARGET                  Read by number, id, title fragment, or path
lookup WORD                  Look up a word
dict-import PATH             Import a Yomitan dictionary zip or folder
dict-list [TYPE]             List Term / Frequency / Pitch dictionaries
dict-order TYPE FROM TO      Reorder dictionaries inside one type
dict-toggle TYPE INDEX [on|off] Enable or disable a dictionary
card WORD                    Write CSV or send to AnkiConnect
stats                        Show reading statistics
sync [auto|export|import]    Sync reading progress
settings                     Open settings
doctor                       Check runtime environment
update                       Check GitHub Releases for updates
```

Chinese aliases such as `菜单`, `导入`, `书架`, `阅读`, `查词`, `导入词典`, `制卡`, `统计`, `同步`, `设置`, `诊断`, and `检查更新` are also supported.

## From Source

```bash
python3 -m pip install -e .
hoshi
```

Run without installing:

```bash
python3 -m hoshi_terminal menu
```

## Data Directory

- Windows: `%APPDATA%\HoshiReaderTerminal`
- macOS: `~/Library/Application Support/HoshiReaderTerminal`
- Linux: `~/.local/share/hoshi-reader-terminal`

Portable run:

```bash
HOSHI_TERMINAL_HOME=.hoshi-terminal python3 -m hoshi_terminal shelf
```

## Development

```bash
python3 -m unittest discover -s tests
python3 scripts/generate_readme_assets.py
python3 scripts/build_packages.py
```

Release packages can be generated with `scripts/build_packages.py`. Releases ship the three portable OS packages plus one-click install scripts.

## Privacy And Data

Hoshi Reader Terminal stores imported books, dictionaries, card CSV files, reading progress, highlights, statistics, and settings locally in its data directory. Sync uses a user-configured local folder. Anki card creation only contacts the configured AnkiConnect endpoint.

## Attribution

The menu, reader, dictionary, Anki, and sync behavior follow Hoshi Reader iOS / Android where it makes sense for a terminal. Terminal-compatible interaction structure is adapted from upstream behavior, while the cross-platform CLI layer is implemented in Python here.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
