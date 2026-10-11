param(
    [string]$ManagedDirectory,
    [string]$Compiler = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$output = Join-Path $PSScriptRoot 'output'
New-Item -ItemType Directory -Force -Path $output | Out-Null
& $Compiler /nologo /warnaserror /target:exe "/out:$output\RegressionTests.exe" "$repo\MySQLWhitelist.cs" "$PSScriptRoot\RegressionTests.cs"
if ($LASTEXITCODE -ne 0) { throw 'Regression test compilation failed' }
& "$output\RegressionTests.exe"
if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed' }
if ($ManagedDirectory) {
    $references = 'Oxide.Core.dll', 'Oxide.CSharp.dll', 'Oxide.MySql.dll', 'Oxide.References.dll' |
        ForEach-Object { "/reference:$(Join-Path $ManagedDirectory $_)" }
    & $Compiler /nologo /warnaserror /target:library "/out:$output\MySQLWhitelist.dll" @references "$repo\MySQLWhitelist.cs"
    if ($LASTEXITCODE -ne 0) { throw 'Oxide API compilation failed' }
    Write-Output 'PASS: Compilation against supplied Oxide assemblies'
}
