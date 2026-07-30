# STREAMVAULT dashboard installer and launcher
# Run this script from the project folder in PowerShell.

$ErrorActionPreference = "Stop"

Write-Host "Checking project folder..." -ForegroundColor Cyan

if (-not (Test-Path ".\.venv")) {
    Write-Host "Creating virtual environment..."
    py -m venv .venv
}

Write-Host "Activating virtual environment..."
& ".\.venv\Scripts\Activate.ps1"

Write-Host "Installing required packages..."
python -m pip install --upgrade pip
python -m pip install streamlit pandas

if (Test-Path ".\netflix_titles(1).csv") {
    Copy-Item ".\netflix_titles(1).csv" ".\netflix_titles.csv" -Force
    Write-Host "Renamed dataset to netflix_titles.csv"
}

if (-not (Test-Path ".\streamvault_dashboard.py")) {
    Write-Host "ERROR: streamvault_dashboard.py is not in this folder." -ForegroundColor Red
    exit 1
}

Write-Host "Launching STREAMVAULT..." -ForegroundColor Green
python -m streamlit run .\streamvault_dashboard.py
