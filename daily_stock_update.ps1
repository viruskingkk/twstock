$ErrorActionPreference = "Stop"

$WorkDir = "D:\twstock"
$BatFile = "D:\twstock\download_common_stocks_with_capital.bat"
$SourceFile = "D:\twstock\history.csv"
$HistoryDir = "D:\twstock\history"

$DateStr = Get-Date -Format "MMdd"
$TargetFile = Join-Path $HistoryDir ("history" + $DateStr + ".csv")

try {

    Write-Host "========================================="
    Write-Host "TWStock Daily Update"
    Write-Host ("Date: " + $DateStr)
    Write-Host "========================================="

    if (-not (Test-Path $BatFile)) {
        throw ("BAT file not found: " + $BatFile)
    }

    Set-Location $WorkDir

    Write-Host ""
    Write-Host "[1/5] Run BAT"

    $Process = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/c `"$BatFile`"" `
        -WorkingDirectory $WorkDir `
        -Wait `
        -PassThru

    if ($Process.ExitCode -ne 0) {
        throw ("BAT failed. ExitCode=" + $Process.ExitCode)
    }

    Write-Host "BAT completed"

    Write-Host ""
    Write-Host "[2/5] Check history.csv"

    if (-not (Test-Path $SourceFile)) {
        throw ("history.csv not found: " + $SourceFile)
    }

    if (-not (Test-Path $HistoryDir)) {
        New-Item -ItemType Directory -Path $HistoryDir -Force | Out-Null
    }

    if (Test-Path $TargetFile) {
        Write-Host ("Target exists, overwrite: " + $TargetFile)
        Remove-Item -Path $TargetFile -Force
    }

    Move-Item `
        -Path $SourceFile `
        -Destination $TargetFile `
        -Force

    Write-Host ("Moved to: " + $TargetFile)

    Write-Host ""
    Write-Host "[3/5] git add"

    git add .

    if ($LASTEXITCODE -ne 0) {
        throw "git add failed"
    }

    $GitStatus = git status --porcelain

    if ([string]::IsNullOrWhiteSpace($GitStatus)) {
        Write-Host "No git changes"
        exit 0
    }

    Write-Host ""
    Write-Host ("[4/5] git commit -m " + $DateStr)

    git commit -m $DateStr

    if ($LASTEXITCODE -ne 0) {
        throw "git commit failed"
    }

    Write-Host ""
    Write-Host "[5/5] git push"

    git push

    if ($LASTEXITCODE -ne 0) {
        throw "git push failed"
    }

    Write-Host ""
    Write-Host "========================================="
    Write-Host "SUCCESS"
    Write-Host ("File: " + $TargetFile)
    Write-Host ("Commit: " + $DateStr)
    Write-Host "========================================="

}
catch {

    Write-Host ""
    Write-Host "========================================="
    Write-Host "FAILED"
    Write-Host $_.Exception.Message
    Write-Host "========================================="

    exit 1
}