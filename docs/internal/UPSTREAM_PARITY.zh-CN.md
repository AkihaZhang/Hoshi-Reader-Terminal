# 上游功能复刻对照

此文档是内部实现对照，不放进 GitHub 首页说明。公共 README 只写安装、截图和用户可直接使用的功能。

## 最新源码基线

- iOS: `Manhhao/Hoshi-Reader` `develop` at `172577c1e399`
- Android: `HuangAntimony/Hoshi-Reader-Android` `main` at `27fcbfabbd43`
- hoshidicts bridge: `Manhhao/hoshidicts-kotlin-bridge` `main` at `b0172987d9da`
- lue audio reference: `superstarryeyes/lue` `main` at `ebcf94ae94fe`
- Terminal current baseline before this slice: `cb0ea55f63b8`

## 复刻规则

- 先看上游源码和测试，再改终端版。
- 能在终端稳定成立的功能做终端等价实现。
- 依赖移动端系统 UI、WebView 几何、系统媒体控件或 Google OAuth 的功能，要么降级为命令行等价物，要么标为暂不复刻。
- GitHub 首页不能写本地路径、研发判断、未实现细节、过度玩笑或会误导用户的“已完全复刻”描述。

## 功能矩阵

| 上游功能组 | 最新源码入口 | 终端版状态 | 下一步 |
| --- | --- | --- | --- |
| 主导航 | Android `navigation/AppShell.kt`, iOS `ShelfView/DictionarySearchView/Settings` | 已按 `书库 / 查词 / 设置` 三入口实现。 | 保持菜单结构，不再单独放重复的阅读入口。 |
| 书库进入阅读 | Android `BookshelfView.kt`, iOS `ShelfView.swift` | 已实现：书架输入数字、标题片段或 id 打开阅读，支持最近阅读/标题排序。 | 继续补批量选择。 |
| 书籍导入 | Android `MultipleFileImportContent`, `ImportDirectoryScanner`; iOS `BookshelfViewModel.importBooks` | 已实现单文件和目录扫描导入，支持 epub/txt/md/html/xhtml。 | 目录导入错误汇总继续对齐 Android 批量导入提示。 |
| 书籍上下文菜单 | Android 长按书籍：重命名、删除、移动、同步、匹配有声书、标记已读 | 已实现重命名、删除、标记已读、移动到书架、同步本书、匹配 Sasayaki。 | `批量选择` 待实现。 |
| 书架分组 | Android `BookShelf`, iOS `BookShelf` | 已实现自定义书架、移动书籍、删除/重排书架、未归类和正在阅读分组。 | 折叠状态和批量移动待实现。 |
| 阅读器分页 | Android `ReaderWebView`, `ReaderPaginationScripts`; iOS `ReaderWebView` | 已实现终端分页、方向键翻页、章节目录和百分比跳转。 | 继续补阅读器外观入口。 |
| 阅读器菜单 | Android `ReaderMenuDestination`, iOS `ActiveSheet` | 已有查词、制卡、划线、划线列表跳转、正文搜索、统计、Sasayaki 详情和章节跳转。 | 补阅读器内外观面板。 |
| 竖排 | Android/iOS WebView writing mode | 已有终端 cell 宽度竖排；汉字/假名按双宽，标点窄化。 | 继续修实际字体不等宽时的降级提示。 |
| 查词核心 | Android `DictionaryNativeBridge`, hoshidicts bridge; iOS `LookupEngine` | 当前是 Python/SQLite Yomitan 实现，不是直接链接 JNI/C++ bridge。Term/Frequency/Pitch、优先级、启停、分页、颜色 badge 已有。 | 长文本扫描、去重、频率排序、IPA/pitch 字段继续向 hoshidicts 对齐。 |
| 查词弹窗体验 | Android `LookupPopupHtml`, `ReaderLookupPopupBridge`; iOS `PopupView` | 终端版用分页文本结果等价，不做 WebView 坐标弹窗。 | 继续优化颜色层级、折叠/展开、递归查词。 |
| 推荐词典和词典更新 | iOS `DictionaryManager.importRecommendedDictionaries`, auto update; Android `DictionaryViewModel` | 未实现推荐下载和自动词典更新。 | 加推荐词典索引、手动更新、自动更新间隔。 |
| 自定义 CSS | Android/iOS dictionary custom CSS | 终端无意义，不复刻。 | 不做。 |
| Anki 后端 | Android `features/anki`, iOS `AnkiManager` | 已支持 CSV 和 AnkiConnect，默认 Lapis 字段，支持词语音频和 Sasayaki 句子音频。 | 补重复检查范围、更多 glossary handlebar、配置获取。 |
| 音频源 | Android `AudioSettings`, `LocalAudioSourceConfig`; iOS `LocalFileServer` | 已支持在线音频源和 `android.db` 本地音频。 | 对齐 Android 的本地音频 source config 文件。 |
| Sasayaki 匹配 | Android/iOS `SasayakiMatcher`, `SasayakiParser` | 已实现 SRT parse、正文过滤、顺序匹配、匹配率。 | 增加更完整的匹配诊断和低置信字幕跳过测试。 |
| Sasayaki 播放 | Android `SasayakiPlaybackController`, iOS `SasayakiPlayer`; lue player参考 | 已实现 mpv/ffplay 播放、上一句/下一句、播放暂停、延迟、倍速、跟随音频翻页和高亮。 | 补 5/10/15/30 秒跳转模式、自动暂停查词、错误恢复。 |
| Sasayaki 制卡音频 | Android `SasayakiCueAudioExporter`, iOS `cueSentenceAudio` | 已能导出 cue 范围音频并写入 Anki 字段。 | 继续对齐多句扩展范围和 AAC/ADTS 重写边界。 |
| 阅读统计 | Android/iOS Statistics | 已记录字符、阅读时间、速度和 TTU 统计文件。 | 补会话/今日/全部分层展示和 autostart 设置。 |
| TTU 同步 | iOS `TTUSYNC.md`, `GoogleDriveHandler`; Android sync queue | 已实现本地 `ttu-reader-data` 进度/统计导入导出。 | Google Drive、bookdata zip、Sasayaki last position sync 未实现。 |
| 备份 | iOS/Android Backup | 已实现数据目录外备份，避免备份包递归包含自己。 | 补按类别备份/恢复。 |
| 外观设置 | Android/iOS Appearance | 终端版仅有语言和横/竖排。 | 增加主题色、读者字号/页宽/页高等终端有效项。 |
| 更新 | Android `features/update`, terminal `updates.py` | 已支持检查 GitHub Release 和便携包就地更新。 | 保持检查和安装分开，增加失败回滚提示。 |

## 当前切片验证要求

- `python3 -m unittest discover -s tests`
- 伪终端流程：`hoshi -> 书库 -> 书架阅读 -> 阅读器查词/制卡/统计/Sasayaki 控制 -> 退出保存`
- 包内容检查：不得包含本地小说、词典、`android.db`、上游源码克隆目录。
