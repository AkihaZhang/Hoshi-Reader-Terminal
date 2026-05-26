# Hoshi Reader Terminal ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey) ![Standalone](https://img.shields.io/badge/standalone-no%20Python%20needed-3fb6e8) ![License](https://img.shields.io/badge/license-MIT-blue)

**English** | [简体中文](README.zh-CN.md)

A terminal Japanese EPUB reader inspired by [Hoshi Reader iOS](https://github.com/Manhhao/Hoshi-Reader) and [Hoshi Reader Android](https://github.com/HuangAntimony/Hoshi-Reader-Android), with bookshelf management, Yomitan lookup, Anki card creation, reading statistics, and local progress sync.

Regular Hoshi is a little too comfortable, so this version moves light-novel reading, dictionary lookup, card creation, and sync into the terminal for a more cyber-ascetic workflow.

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
- Switch between horizontal text and a simple terminal vertical-text mode.
- Use clear reader commands with examples shown on screen:
  - `/読みました` for lookup
  - `a 読む` for card creation
  - `h note` for highlight notes

### Lookup

- Import Yomitan dictionaries from folders or zip files.
- Search from the Dictionary menu, the command line, or inside the reader.
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

## Download

Download standalone packages from [GitHub Releases](https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/tag/v0.1.2). Standalone packages include the runtime and do not require Python.

| OS | Package |
| --- | --- |
| Windows | `Hoshi-Reader-Terminal-0.1.2-windows-standalone.zip` |
| macOS | `Hoshi-Reader-Terminal-0.1.2-macos-standalone.tar.gz` |
| Linux | `Hoshi-Reader-Terminal-0.1.2-linux-standalone.tar.gz` or `hoshi-reader-terminal_0.1.2_amd64.deb` |

After installation, run:

```bash
hoshi
```

## Package Managers

```bash
# macOS / Linuxbrew
brew install AkihaZhang/Hoshi-Reader-Terminal/hoshi-reader-terminal

# Windows / Scoop
scoop bucket add hoshi-reader-terminal https://github.com/AkihaZhang/Hoshi-Reader-Terminal
scoop install hoshi-reader-terminal

# Debian / Ubuntu
sudo apt install ./hoshi-reader-terminal_0.1.2_amd64.deb
```

## Commands

```text
menu                         Open main menu
import PATH                  Import a book
shelf                        Show bookshelf
read TARGET                  Read by number, id, title fragment, or path
lookup WORD                  Look up a word
dict-import PATH             Import a Yomitan dictionary zip or folder
card WORD                    Write CSV or send to AnkiConnect
stats                        Show reading statistics
sync [auto|export|import]    Sync reading progress
settings                     Open settings
doctor                       Check runtime environment
```

Chinese aliases such as `菜单`, `导入`, `书架`, `阅读`, `查词`, `导入词典`, `制卡`, `统计`, `同步`, `设置`, and `诊断` are also supported.

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

Tagged releases are built by GitHub Actions with PyInstaller on Windows, macOS, and Linux. The Linux job also publishes a `.deb` package.

## Privacy And Data

Hoshi Reader Terminal stores imported books, dictionaries, card CSV files, reading progress, highlights, statistics, and settings locally in its data directory. Sync uses a user-configured local folder. Anki card creation only contacts the configured AnkiConnect endpoint.

## Attribution

The menu, reader, dictionary, Anki, and sync shapes are inspired by Hoshi Reader iOS / Android. This repository does not copy upstream source code; it is a terminal parody implementation.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
