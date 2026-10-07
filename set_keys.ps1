# Adds the API keys to Vercel as encrypted environment variables.
# Keys are read interactively, so they are never stored in this repo or in chat.
# Usage (from this folder):  powershell -ExecutionPolicy Bypass -File .\set_keys.ps1

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command vercel.cmd -ErrorAction SilentlyContinue)) {
    throw 'Vercel CLI not found. Install it with: npm i -g vercel'
}

vercel.cmd whoami | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Not logged in to Vercel. Run: vercel.cmd login'
}

$gemini = Read-Host 'Gemini API key (AIza...)'
if (-not $gemini) { throw 'Gemini key is required.' }

$plantId = Read-Host 'Plant.id API key'
if (-not $plantId) { throw 'Plant.id key is required.' }

$model = Read-Host 'Gemini narrative model [gemini-3.5-flash]'
if (-not $model) { $model = 'gemini-3.5-flash' }

$vars = @{
    VISION_API_KEY           = $gemini
    VISION_BASE_URL          = 'https://generativelanguage.googleapis.com/v1beta/openai/'
    VISION_MODEL             = $model
    VISION_FALLBACK_MODELS   = 'gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3-flash-preview'
    VISION_SUPPORTS_IMAGES   = '1'
    PLANT_ID_API_KEY         = $plantId
}

foreach ($name in $vars.Keys) {
    Write-Host "Setting $name ..."
    vercel.cmd env rm $name production --yes 2>$null | Out-Null
    vercel.cmd env add $name production --value $vars[$name] --sensitive --yes | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to set $name" }
}

Write-Host ''
Write-Host 'Keys stored. Redeploying...' -ForegroundColor Green
vercel.cmd deploy --prod
Write-Host ''
Write-Host 'Done. Open https://tomato-leaf-vercel.vercel.app' -ForegroundColor Green