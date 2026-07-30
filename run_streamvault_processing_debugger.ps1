# STREAMVAULT country-processing batch debugger
# Run this file from the STREAMVAULT project directory.

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "STREAMVAULT Processing Debugger" -ForegroundColor Cyan
Write-Host "================================"

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    Write-Host "Activating .venv..."
    & ".\.venv\Scripts\Activate.ps1"
}

python -m pip install pandas

$CsvCandidates = @(
    ".\netflix_titles.csv",
    ".\netflix_titles(1).csv"
)

$CsvPath = $null

foreach ($Candidate in $CsvCandidates) {
    if (Test-Path $Candidate) {
        $CsvPath = $Candidate
        break
    }
}

if (-not $CsvPath) {
    $CsvPath = Get-ChildItem -Path . -Filter "*.csv" |
        Select-Object -First 1 -ExpandProperty FullName
}

if (-not $CsvPath) {
    Write-Host "ERROR: No CSV file was found in this folder." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".\streamvault_processing_debugger.py")) {
    Write-Host "ERROR: streamvault_processing_debugger.py is missing." -ForegroundColor Red
    exit 1
}

Write-Host "Dataset: $CsvPath" -ForegroundColor Green
Write-Host "Scanning all Python files in: $(Get-Location)"
Write-Host ""

python .\streamvault_processing_debugger.py `
    --csv "$CsvPath" `
    --project "." `
    --output ".\streamvault_processing_debug"

Write-Host ""
Write-Host "Opening the readable report..." -ForegroundColor Green
notepad ".\streamvault_processing_debug\processing_trace.txt"
