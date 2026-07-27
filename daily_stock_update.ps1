$ErrorActionPreference = "Stop"

$WorkDir = "D:\twstock"
$BatFile = "download_common_stocks_with_capital.bat"
$SourceFile = Join-Path $WorkDir "history.csv"
$HistoryDir = Join-Path $WorkDir "history"
$DateText = Get-Date -Format "MMdd"
$TargetFile = Join-Path $HistoryDir ("history" + $DateText + ".csv")
$LogFile = Join-Path $WorkDir "daily_stock_update.log"

function Write-Log {
    param([string]$Message)

    $Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $Line = "[" + $Time + "] " + $Message

    Write-Host $Line
    Add-Content -LiteralPath $LogFile -Value $Line -Encoding ASCII
}

try {
    Write-Log "========================================"
    Write-Log "Daily stock update started"

    Set-Location -LiteralPath $WorkDir

    $BatPath = Join-Path $WorkDir $BatFile

    if (-not (Test-Path -LiteralPath $BatPath)) {
        throw ("BAT file not found: " + $BatPath)
    }

    if (-not (Test-Path -LiteralPath $HistoryDir)) {
        New-Item -ItemType Directory -Path $HistoryDir -Force | Out-Null
    }

    if (Test-Path -LiteralPath $SourceFile) {
        Write-Log "Removing old history.csv"
        Remove-Item -LiteralPath $SourceFile -Force
    }

    Write-Log ("Running: " + $BatFile)

    & cmd.exe /d /c "call `"$BatPath`""

    $BatExitCode = $LASTEXITCODE

    if ($BatExitCode -ne 0) {
        throw ("Downloader failed. Exit code: " + $BatExitCode)
    }

    Write-Log "Downloader completed"

    if (-not (Test-Path -LiteralPath $SourceFile)) {
        throw ("history.csv was not created: " + $SourceFile)
    }

    if (Test-Path -LiteralPath $TargetFile) {
        Write-Log ("Replacing existing file: " + $TargetFile)
        Remove-Item -LiteralPath $TargetFile -Force
    }

    Move-Item -LiteralPath $SourceFile -Destination $TargetFile -Force

    Write-Log ("Saved: " + $TargetFile)

    Write-Log "Running git add"
    & git add .

    if ($LASTEXITCODE -ne 0) {
        throw "git add failed"
    }

    $Changes = & git status --porcelain

    if (($Changes | Measure-Object).Count -eq 0) {
        Write-Log "No Git changes detected"
        Write-Log "========================================"
        exit 0
    }

    Write-Log ("Running git commit: " + $DateText)
    & git commit -m $DateText

    if ($LASTEXITCODE -ne 0) {
        throw "git commit failed"
    }

    Write-Log "Running git push"
    & git push

    if ($LASTEXITCODE -ne 0) {
        throw "git push failed"
    }

    Write-Log "Daily stock update completed"
    Write-Log "========================================"
    exit 0
}
catch {
    Write-Log ("ERROR: " + $_.Exception.Message)
    Write-Log "========================================"
    exit 1
}
