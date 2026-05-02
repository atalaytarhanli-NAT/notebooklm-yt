<#
.SYNOPSIS
    Tek komutla NotebookLM cookie'sini yenile + Render'a push et.

.DESCRIPTION
    1. Tarayıcı açar → Google'a giriş yaparsın
    2. storage_state.json'ı okur
    3. Deploy edilmiş app'e POST eder → app, Render API üzerinden env var'ı update eder
    4. Render otomatik redeploy başlatır
    5. /api/auth/check ok dönene kadar bekler

.PARAMETER AppUrl
    Deploy edilmiş app URL'i. Default: env var APP_URL veya https://notebooklm-yt.onrender.com

.PARAMETER AppToken
    Bearer token. Default: env var APP_TOKEN

.EXAMPLE
    $env:APP_TOKEN = "b_XK1Tn4OOJX..."
    .\scripts\refresh-cookie.ps1
#>

[CmdletBinding()]
param(
    [string]$AppUrl  = $(if ($env:APP_URL) { $env:APP_URL } else { "https://notebooklm-yt.onrender.com" }),
    [string]$AppToken = $env:APP_TOKEN,
    [switch]$SkipLogin
)

$ErrorActionPreference = "Stop"

if (-not $AppToken) {
    Write-Error "APP_TOKEN env var bos. Calistirmadan once: `$env:APP_TOKEN = 'your-token'"
    exit 1
}

$storagePath = Join-Path $env:USERPROFILE ".notebooklm\storage_state.json"

if (-not $SkipLogin) {
    Write-Host "[1/4] notebooklm login -> tarayicida Google girisini tamamla..." -ForegroundColor Cyan
    notebooklm login
    if ($LASTEXITCODE -ne 0) {
        Write-Error "notebooklm login basarisiz."
        exit 1
    }
}

if (-not (Test-Path $storagePath)) {
    Write-Error "storage_state.json bulunamadi: $storagePath"
    exit 1
}

Write-Host "[2/4] storage_state.json okunuyor..." -ForegroundColor Cyan
$json = (Get-Content $storagePath -Raw) -replace "`r`n", ""
$json = $json -replace "`n", ""
Write-Host "    boyut: $($json.Length) char, cookie: $((($json | ConvertFrom-Json).cookies).Count) adet" -ForegroundColor Gray

Write-Host "[3/4] $AppUrl/api/admin/refresh-auth -> POST..." -ForegroundColor Cyan
$body = @{ storage_state = $json } | ConvertTo-Json -Compress
try {
    $response = Invoke-RestMethod `
        -Uri "$AppUrl/api/admin/refresh-auth" `
        -Method POST `
        -Headers @{ Authorization = "Bearer $AppToken"; "Content-Type" = "application/json" } `
        -Body $body
    Write-Host "    OK: $($response.message)" -ForegroundColor Green
} catch {
    Write-Error "Refresh basarisiz: $($_.Exception.Message)"
    if ($_.ErrorDetails.Message) {
        Write-Host "Server response: $($_.ErrorDetails.Message)" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host "[4/4] Render redeploy bekleniyor (1-2 dk)..." -ForegroundColor Cyan
$maxAttempts = 20
$delaySeconds = 15
for ($i = 1; $i -le $maxAttempts; $i++) {
    Start-Sleep -Seconds $delaySeconds
    try {
        $check = Invoke-RestMethod `
            -Uri "$AppUrl/api/auth/check" `
            -Headers @{ Authorization = "Bearer $AppToken" } `
            -TimeoutSec 10
        if ($check.ok -eq $true) {
            Write-Host ""
            Write-Host "BASARILI! Auth gecerli, $($check.notebook_count) notebook listeli." -ForegroundColor Green
            Write-Host "URL: $AppUrl" -ForegroundColor Green
            exit 0
        }
        Write-Host "    deneme ${i}/${maxAttempts}: hala redeploy bekliyor" -ForegroundColor Gray
    } catch {
        Write-Host "    deneme ${i}/${maxAttempts}: server geciici cevap vermiyor (redeploy devam ediyor)" -ForegroundColor Gray
    }
}

Write-Warning "Timeout: redeploy 5 dk icinde tamamlanmadi. Render Dashboard'dan kontrol et."
exit 1
