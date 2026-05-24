param(
    [string]$Registry = "sources/external.yml",
    [string]$OutRoot = "runs/auto",
    [string]$Pack = ""
)

$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Out = Join-Path $OutRoot $Stamp
$Args = @("alpha", "run", $Registry, "--out", $Out)

if ($Pack -ne "") {
    $Args += @("--pack", $Pack)
}

python -m semscrape.cli @Args
