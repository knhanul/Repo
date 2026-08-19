$ErrorActionPreference = "Stop"

# 프로젝트 루트
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# 출력 폴더
$DistDir = Join-Path $ProjectRoot "dist"

# 임시 작업 폴더
$TempDir = Join-Path $env:TEMP "nuni-repo-deploy"

# 파일명용 타임스탬프
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

# 최종 ZIP 파일
$ZipFile = Join-Path $DistDir "repo-update-$Timestamp.zip"

Write-Host ""
Write-Host "======================================"
Write-Host " NUNI Repository Deploy ZIP"
Write-Host "======================================"
Write-Host ""

if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force
}

New-Item -ItemType Directory -Path $TempDir | Out-Null

if (!(Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
}

Write-Host "[1/3] 배포 파일 복사..."

robocopy $ProjectRoot $TempDir /E `
    /XD `
        ".git" `
        ".venv" `
        "__pycache__" `
        ".pytest_cache" `
        "data" `
        "dist" `
    /XF `
        ".env" `
        ".env.*" `
        "*.pyc" `
        "*.pyo" `
        "*.log"

# robocopy는 0~7을 정상 상태로 사용
if ($LASTEXITCODE -gt 7) {
    throw "robocopy 실패. ExitCode: $LASTEXITCODE"
}

Write-Host "[2/3] ZIP 생성..."

Compress-Archive `
    -Path "$TempDir\*" `
    -DestinationPath $ZipFile `
    -CompressionLevel Optimal `
    -Force

Write-Host "[3/3] 임시 파일 정리..."

Remove-Item $TempDir -Recurse -Force

Write-Host ""
Write-Host "배포 ZIP 생성 완료"
Write-Host $ZipFile
Write-Host ""