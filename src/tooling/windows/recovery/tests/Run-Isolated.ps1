param([string]$Base = (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'AgentHUDPrivate\recovery-tests'))
$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$source = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..\crates\host\src\recovery\windows')).Path
$run = Join-Path $base ([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
$bin = Join-Path $run 'bin'
$data = Join-Path $run 'data'
New-Item -ItemType Directory -Path $bin, $data -Force | Out-Null
$junction = Join-Path $run 'junction'
$target = Join-Path $run 'junction-target'
New-Item -ItemType Directory -Path $target | Out-Null
try {
    New-Item -ItemType Junction -Path $junction -Target $target -ErrorAction Stop | Out-Null
} catch {
    $junction = '-'
    Write-Host "SKIP reparse creation: $($_.Exception.Message)"
}
$fixture = Join-Path $bin 'RecoveryFixture.exe'
$test = Join-Path $bin 'RecoveryTests.exe'
& $compiler /nologo /target:exe "/out:$fixture" /r:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'Fixture.cs')
if ($LASTEXITCODE -ne 0) { throw 'Fixture compilation failed.' }
$core = @(Get-ChildItem -LiteralPath $source -Filter '*.cs' | ForEach-Object { $_.FullName })
if ($core.Count -eq 0) { throw 'No recovery core source files found.' }
& $compiler /nologo /target:exe /main:Tests "/out:$test" /r:System.Web.Extensions.dll /r:System.Windows.Forms.dll $core (Join-Path $PSScriptRoot 'Tests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Test compilation failed.' }
Write-Host "Isolated evidence: $run"
& $test $data $junction 2>&1 | Tee-Object -FilePath (Join-Path $run 'results.txt')
$result = $LASTEXITCODE
Write-Host "Test exit: $result"
exit $result
