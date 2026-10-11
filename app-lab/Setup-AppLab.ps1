param([string]$RuntimeRoot = $env:CMDBOX_LAB_RUNTIME_ROOT)
$ErrorActionPreference = 'Stop'
$labProject = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) { $RuntimeRoot = Join-Path $labProject 'runtimes' }
$env:CMDBOX_LAB_RUNTIME_ROOT = $RuntimeRoot
$labPython = Join-Path $RuntimeRoot 'python312\python.exe'
if (-not (Test-Path -LiteralPath $labPython)) { throw 'First run Setup-ADK.ps1.' }
& $labPython -X utf8 -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: --require-hashes --no-deps --upgrade --target (Join-Path $RuntimeRoot 'app-deps') --cache-dir (Join-Path $RuntimeRoot 'pip-cache') -r (Join-Path $PSScriptRoot 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Isolated application dependency installation failed.' }
& $labPython -X utf8 (Join-Path $PSScriptRoot 'prepare_tokenizer.py')
if ($LASTEXITCODE -ne 0) { throw 'Pinned tokenizer setup failed.' }
