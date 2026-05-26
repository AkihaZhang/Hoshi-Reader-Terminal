<h1 align="center">Hoshi Reader Terminal</h1>

<p align="center">在终端里启动 Hoshi：书库、阅读、查词、Anki、统计和进度同步。<br>Run Hoshi in your terminal: library, reading, lookup, Anki, stats, and progress sync.</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3fb6e8?style=flat-square">
  <img alt="Platforms" src="https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-terminal-5ed6b3?style=flat-square">
  <img alt="Version" src="https://img.shields.io/badge/version-0.1.1-f4c95d?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-d8dee9?style=flat-square">
</p>

<p align="center">
  <img src="docs/images/01-menu.svg" alt="Hoshi Reader Terminal main menu" width="760">
</p>

普通 Hoshi 太像娱乐软件，不够赛博苦行僧。Hoshi Reader Terminal 把轻小说阅读、查词、挖卡和进度同步塞进终端，让你假装自己是 Unix 老登，也顺手解决 Hoshi 过于好用的问题。

Regular Hoshi feels a little too comfortable, almost too much like an entertainment app. Hoshi Reader Terminal moves light-novel reading, dictionary lookup, card mining, and progress sync into the terminal, for the cyber-ascetic who wants to pretend they are an old Unix hand while solving the problem that Hoshi is simply too usable.

Hoshi Reader Terminal 能在 Windows、macOS、Linux 主流终端里运行，参考了 [Hoshi Reader iOS](https://github.com/Manhhao/Hoshi-Reader) 和 [Hoshi Reader Android](https://github.com/HuangAntimony/Hoshi-Reader-Android) 的页面结构，把适合终端的功能做成 `hoshi` 命令。

Hoshi Reader Terminal runs in mainstream Windows, macOS, and Linux terminals. It follows the structure of [Hoshi Reader iOS](https://github.com/Manhhao/Hoshi-Reader) and [Hoshi Reader Android](https://github.com/HuangAntimony/Hoshi-Reader-Android), then keeps the parts that make sense in a terminal behind a single `hoshi` command.

## 功能展示 / Showcase

| 阅读 / Reader | 查词 / Dictionary |
| --- | --- |
| <img src="docs/images/02-reader.svg" alt="reader screenshot"> | <img src="docs/images/03-dictionary.svg" alt="dictionary screenshot"> |

| 同步 / Sync | 设置 / Settings |
| --- | --- |
| <img src="docs/images/04-sync.svg" alt="sync screenshot"> | <img src="docs/images/05-settings.svg" alt="settings screenshot"> |

## 已实现 / Features

- `hoshi` 直接启动主菜单，菜单结构参考 Hoshi：书库、查词、设置。
- Launch the main menu with `hoshi`; the menu structure follows Hoshi: books, dictionary, and settings.
- 支持 `.epub`、`.txt`、`.md`、`.html`、`.xhtml` 书籍导入和阅读。
- Import and read `.epub`, `.txt`, `.md`, `.html`, and `.xhtml` books.
- 书库会记录阅读进度、阅读统计和划线备注。
- Track reading progress, reading stats, highlights, and notes.
- 支持导入 Yomitan 词典目录或 zip，带简单日语活用还原。
- Import Yomitan dictionary folders or zip files, with lightweight Japanese deinflection.
- 支持 Anki 挖卡：写入 CSV，也可通过 AnkiConnect 直接制卡。
- Mine Anki cards to CSV, or create cards directly through AnkiConnect.
- 小说目录、词典目录、同步目录都能在菜单里设置。
- Configure book, dictionary, and sync directories from the terminal menus.
- 支持界面语言切换：简体中文、English、日本語。
- Switch the interface language between Simplified Chinese, English, and Japanese.
- 阅读进度和统计可导入/导出到本地 `ttu-reader-data` 同步目录。
- Import and export progress and stats through a local `ttu-reader-data` sync folder.
- 不依赖第三方 Python 包，Python 3.10+ 即可运行。
- No third-party Python dependencies; Python 3.10+ is enough.

## 安装包 / Downloads

仓库内已经生成三种系统的便携包，也可以从 [Releases](https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/tag/v0.1.1) 下载同一批安装包。

Portable packages for the three major desktop operating systems are included in the repository and also available from [Releases](https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/tag/v0.1.1).

| 系统 / OS | 安装包 / Package |
| --- | --- |
| Windows | [`dist/Hoshi-Reader-Terminal-0.1.1-windows.zip`](dist/Hoshi-Reader-Terminal-0.1.1-windows.zip) |
| macOS | [`dist/Hoshi-Reader-Terminal-0.1.1-macos.tar.gz`](dist/Hoshi-Reader-Terminal-0.1.1-macos.tar.gz) |
| Linux | [`dist/Hoshi-Reader-Terminal-0.1.1-linux.tar.gz`](dist/Hoshi-Reader-Terminal-0.1.1-linux.tar.gz) |

安装后打开终端输入：

After installation, open a terminal and run:

```bash
hoshi
```

从源码安装：

Install from source:

```bash
python3 -m pip install -e .
hoshi
```

不安装也可以直接跑：

Run without installing:

```bash
python3 -m hoshi_terminal menu
```

## 快速体验 / Quick Start

```bash
hoshi
python3 -m hoshi_terminal 导入 examples/demo_book.txt
python3 -m hoshi_terminal 书架
python3 -m hoshi_terminal 阅读 1 --print
python3 -m hoshi_terminal 导入词典 examples/mini-yomitan
python3 -m hoshi_terminal 查词 読みました
python3 -m hoshi_terminal 挖矿 読む --sentence "端末で読むと、学習している気分だけは出る。"
python3 -m hoshi_terminal 同步 export --path ~/Documents/HoshiReaderTerminalSync
```

## 主菜单 / Main Menu

```text
Hoshi Reader
1. 书库
2. 查词
3. 设置
0. 退出
```

书库里可以导入 EPUB、打开书架、阅读、设置小说目录。书架阅读支持输入数字序号，例如 `1` 打开第一本。查词里可以搜索、导入辞典、查看辞典列表和设置词典目录。设置里包含辞典、Anki、外观、高级、诊断和关于。

The Books menu imports EPUB/text files, opens the shelf, starts reading, and configures the book directory. Shelf reading supports numeric selection, so `1` opens the first book. The Dictionary menu supports lookup, dictionary import, dictionary listing, and dictionary path settings. Settings include dictionary, Anki, appearance, advanced tools, diagnostics, and about.

## 阅读器按键 / Reader Keys

```text
Enter/n  下一页 / next page
p        上一页 / previous page
v        切换终端纵书模式 / toggle terminal vertical mode
/word    查词 / lookup
a word   从当前页挖词 / mine from current page
h note   给当前页做划线备注 / add highlight note
s        显示本次阅读统计 / show session stats
g 12     跳到第 12 页 / go to page 12
q        退出 / quit
```

## 命令 / Commands

```text
menu / 菜单                         打开主菜单 / open main menu
import / 导入 PATH                  导入书籍 / import a book
shelf / 书架                        查看书架 / show shelf
read / 阅读 TARGET                  阅读书籍序号、id、标题片段或文件路径 / read by number, id, title, or path
lookup / 查词 WORD                  查词 / lookup a word
dict-import / 导入词典 PATH         导入 Yomitan 词典 zip 或目录 / import Yomitan zip or folder
mine / 挖矿 WORD                    写入 CSV 或发送到 AnkiConnect / write CSV or send to AnkiConnect
stats / 统计                        查看阅读统计 / show reading stats
sync / 同步 [auto|export|import]    同步阅读进度 / sync reading progress
settings / 设置                     打开设置 / open settings
doctor / 诊断                       检查运行环境 / check environment
```

## 数据目录 / Data Directory

- Windows: `%APPDATA%\HoshiReaderTerminal`
- macOS: `~/Library/Application Support/HoshiReaderTerminal`
- Linux: `~/.local/share/hoshi-reader-terminal`

便携运行：

Portable run:

```bash
HOSHI_TERMINAL_HOME=.hoshi-terminal python3 -m hoshi_terminal 书架
```

## 开发 / Development

```bash
python3 -m unittest discover -s tests
python3 scripts/generate_readme_assets.py
python3 scripts/build_packages.py
```

## 致谢 / Credits

菜单、阅读、辞典、Anki 和同步的轮廓参考自 Hoshi Reader iOS / Android。这个仓库没有复制上游源码，是一个终端恶搞版实现。

The menu, reader, dictionary, Anki, and sync shapes are inspired by Hoshi Reader iOS / Android. This repository does not copy upstream source code; it is a terminal parody implementation.
