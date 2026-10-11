param([string]$RuntimeRoot = $env:CMDBOX_LAB_RUNTIME_ROOT)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) { $RuntimeRoot = Join-Path $PSScriptRoot 'runtimes' }
$labRuntime = Join-Path $RuntimeRoot 'python312'
$labPins = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'toolchain.json') -Raw -Encoding utf8 | ConvertFrom-Json
New-Item -ItemType Directory -Path $labRuntime -Force | Out-Null
$labZip = Join-Path $labRuntime 'python-embed.zip'
if (-not (Test-Path -LiteralPath $labZip)) { Invoke-WebRequest -Uri $labPins.pythonSource -OutFile $labZip }
if ((Get-FileHash -LiteralPath $labZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $labPins.pythonZipSha256) { throw 'Pinned CPython hash mismatch.' }
$labPython = Join-Path $labRuntime 'python.exe'
if (-not (Test-Path -LiteralPath $labPython)) { Expand-Archive -LiteralPath $labZip -DestinationPath $labRuntime }
$labPipName = "pip-$($labPins.pip)-py3-none-any.whl"
$labPip = Join-Path $labRuntime $labPipName
if (-not (Test-Path -LiteralPath $labPip)) {
  $labMetadata = Invoke-RestMethod -Uri "https://pypi.org/pypi/pip/$($labPins.pip)/json"
  $labWheel = $labMetadata.urls | Where-Object filename -eq $labPipName | Select-Object -First 1
  if (-not $labWheel -or $labWheel.digests.sha256 -ne $labPins.pipWheelSha256) { throw 'Pinned pip metadata mismatch.' }
  Invoke-WebRequest -Uri $labWheel.url -OutFile $labPip
}
if ((Get-FileHash -LiteralPath $labPip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $labPins.pipWheelSha256) { throw 'Pinned pip hash mismatch.' }
Set-Content -LiteralPath (Join-Path $labRuntime 'python312._pth') -Value "python312.zip`n.`nLib\site-packages`n$labPipName`nimport site`n" -Encoding ascii
& $labPython -X utf8 -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: --require-hashes --no-deps --upgrade --target (Join-Path $labRuntime 'Lib\site-packages') --cache-dir (Join-Path $RuntimeRoot 'pip-cache') -r (Join-Path $PSScriptRoot 'adk-requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Isolated ADK installation failed.' }
& $labPython -X utf8 -m pip check
if ($LASTEXITCODE -ne 0) { throw 'ADK dependency consistency check failed.' }
