# Adds the two API keys to Vercel as encrypted environment variables.
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

$groq = Read-Host 'Groq API key (gsk_...)'
if (-not $groq) { throw 'Groq key is required.' }

$plantId = Read-Host 'Plant.id API key'
if (-not $plantId) { throw 'Plant.id key is required.' }

$model = Read-Host 'Groq vision model [llama-3.2-11b-vision-preview]'
if (-not $model) { $model = 'llama-3.2-11b-vision-preview' }

$vars = @{
    VISION_API_KEY    = $groq
    VISION_BASE_URL   = 'https://api.groq.com/openai/v1'
    VISION_MODEL      = $model
    PLANT_ID_API_KEY  = $plantId
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
