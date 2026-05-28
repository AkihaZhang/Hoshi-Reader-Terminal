$ErrorActionPreference = "Stop"

$Repo = "AkihaZhang/Hoshi-Reader-Terminal"
$ApiUrl = "https://api.github.com/repos/$Repo/releases/latest"
$DownloadBase = "https://github.com/$Repo/releases/download"
$Target = Join-Path $env:LOCALAPPDATA "HoshiReaderTerminal\bin"

function Test-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    }
    return $false
}

if (-not (Test-Python)) {
    Write-Host "Hoshi Reader Terminal 需要 Python 3.10+。"
    Write-Host "请先安装 Python 3.10+，然后重新运行本脚本。"
    exit 1
}

$Release = Invoke-RestMethod -Uri $ApiUrl -Headers @{ "User-Agent" = "Hoshi-Reader-Terminal-Installer" }
$Tag = if ($env:HOSHI_VERSION) { $env:HOSHI_VERSION } else { $Release.tag_name }
if (-not $Tag) {
    throw "无法获取最新版本。"
}
$Version = $Tag.TrimStart("v")
$Asset = "Hoshi-Reader-Terminal-$Version-windows.zip"
$Url = "$DownloadBase/$Tag/$Asset"
$Temp = Join-Path ([System.IO.Path]::GetTempPath()) ("hoshi-reader-terminal-" + [System.Guid]::NewGuid().ToString("N"))
$Zip = Join-Path $Temp $Asset
$Unpack = Join-Path $Temp "unpack"

New-Item -ItemType Directory -Force -Path $Temp, $Unpack, $Target | Out-Null
try {
    Write-Host "下载 $Asset"
    Invoke-WebRequest -Uri $Url -OutFile $Zip
    Expand-Archive -Path $Zip -DestinationPath $Unpack -Force
    $Package = Join-Path $Unpack "Hoshi-Reader-Terminal-$Version-windows"
    Copy-Item -Path (Join-Path $Package "hoshi-terminal.pyz") -Destination (Join-Path $Target "hoshi-terminal.pyz") -Force

    $Launcher = @"
@echo off
py -3 "%LOCALAPPDATA%\HoshiReaderTerminal\bin\hoshi-terminal.pyz" %*
if errorlevel 9009 python "%LOCALAPPDATA%\HoshiReaderTerminal\bin\hoshi-terminal.pyz" %*
"@
    Set-Content -Path (Join-Path $Target "hoshi.cmd") -Value $Launcher -Encoding ASCII
    Set-Content -Path (Join-Path $Target "hoshi-terminal.cmd") -Value $Launcher -Encoding ASCII

    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $PathParts = @()
    if ($UserPath) { $PathParts = $UserPath -split ";" }
    if ($PathParts -notcontains $Target) {
        $NewPath = if ($UserPath) { "$UserPath;$Target" } else { $Target }
        [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
        $env:Path = "$env:Path;$Target"
        Write-Host "已加入用户 PATH: $Target"
    }

    Write-Host "安装完成。新开一个终端后运行: hoshi"
    Write-Host "检查更新: hoshi 检查更新"
} finally {
    Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue
}
