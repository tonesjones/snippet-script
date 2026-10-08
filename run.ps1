# Create a local Python environment on first use, then run snippet_check.py with all arguments.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$venvPython = Join-Path $here '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    $py = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
    & $py -3 -m venv (Join-Path $here '.venv')
    if ($LASTEXITCODE -ne 0) { Write-Error 'Could not create .venv; install Python 3.9 or later.'; exit 2 }
    & $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $here 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force (Join-Path $here '.venv'); exit 2 }
}
& $venvPython (Join-Path $here 'snippet_check.py') @args
exit $LASTEXITCODE
