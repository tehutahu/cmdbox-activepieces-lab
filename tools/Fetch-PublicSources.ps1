param([switch]$IncludeActivepiecesSource)
$ErrorActionPreference = 'Stop'
$labProject = Split-Path -Parent $PSScriptRoot
function Get-LabPublicCheckout([string]$Name, [string]$Url, [string]$Pin) {
  $labTarget = Join-Path $labProject $Name
  if (Test-Path -LiteralPath $labTarget) {
    $labHead = & git -C $labTarget rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $labHead -ne $Pin) { throw "Existing $Name does not match the fixed public commit." }
    if ((& git -C $labTarget status --porcelain)) { throw "Existing $Name contains changes; refusing to reset it." }
    return
  }
  New-Item -ItemType Directory -Path $labTarget | Out-Null
  & git -C $labTarget init
  if ($LASTEXITCODE -ne 0) { throw 'Public source init failed.' }
  & git -C $labTarget remote add origin $Url
  if ($LASTEXITCODE -ne 0) { throw 'Public source remote configuration failed.' }
  & git -C $labTarget fetch --depth 1 origin $Pin
  if ($LASTEXITCODE -ne 0) { throw 'Fixed public source fetch failed.' }
  & git -C $labTarget checkout --detach FETCH_HEAD
  if ($LASTEXITCODE -ne 0) { throw 'Fixed public source checkout failed.' }
}
Get-LabPublicCheckout 'cmdbox' 'https://github.com/hamacom2004jp/cmdbox.git' 'a429260512035aa358d49e7b319c2bfc56532742'
if ($IncludeActivepiecesSource) { Get-LabPublicCheckout 'activepieces' 'https://github.com/activepieces/activepieces.git' 'd125d34e59ac57ea4d0df57af4b917344027f06b' }
