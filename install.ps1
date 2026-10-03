<#
.SYNOPSIS
    Install Flying RAG MCP from this checkout: Python 3.12 venv, pinned
    dependencies, the operator's home folder and the MCP client entry.

.DESCRIPTION
    Nothing here is tied to one machine: every path comes from where the
    checkout lies and from the parameters.

      .\install.ps1                              # home = this folder
      .\install.ps1 -HomeDir D:\flying-rag-home  # config and data elsewhere
      .\install.ps1 -Daemon                      # also start the watcher at logon

    The server is tested on Python 3.12 (requirements.lock is a freeze of that
    environment); the installer refuses other versions rather than guess.

.PARAMETER HomeDir
    Folder for config.yaml and data/. Default: this checkout. When set, the
    client entry carries FLYING_RAG_HOME.
.PARAMETER VenvPath
    Where to create the virtual environment. Default: .venv in the checkout.
.PARAMETER SkipDeps
    Do not run pip (the environment already has the dependencies).
.PARAMETER Daemon
    Register a Task Scheduler task that runs the watcher (main.py --daemon) at
    logon for the current user.
#>
param(
    [string]$HomeDir = "",
    [string]$VenvPath = "",
    [switch]$SkipDeps,
    [switch]$Daemon
)

$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
if (-not $VenvPath) { $VenvPath = Join-Path $Repo ".venv" }
$VenvPy = Join-Path $VenvPath "Scripts\python.exe"

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Warn($text) { Write-Host "    ! $text" -ForegroundColor Yellow }

# 1. Python 3.12
if (-not (Test-Path $VenvPy)) {
    Step "Python 3.12"
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) {
        throw "Python launcher 'py' not found. Install Python 3.12: winget install Python.Python.3.12"
    }
    $base = (& py -3.12 -c "import sys; print(sys.executable)") 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $base) {
        throw "Python 3.12 not found (py -3.12). Install it: winget install Python.Python.3.12"
    }
    Step "virtual environment: $VenvPath"
    & py -3.12 -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
$version = & $VenvPy -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($version -ne "3.12") {
    throw "$VenvPath runs Python $version; the server is tested on 3.12. Recreate it with py -3.12."
}

# 2. Dependencies, exactly as tested
if (-not $SkipDeps) {
    Step "dependencies from requirements.lock"
    & $VenvPy -m pip install --upgrade pip --quiet
    & $VenvPy -m pip install -r (Join-Path $Repo "requirements.lock")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

# 3. Operator's home and the client entry
Step "home folder"
$initArgs = @((Join-Path $Repo "main.py"), "--init")
if ($HomeDir) { $initArgs += $HomeDir }
$entry = & $VenvPy @initArgs
if ($LASTEXITCODE -ne 0) { throw "main.py --init failed" }
$resolvedHome = if ($HomeDir) { (Resolve-Path $HomeDir).Path } else { $Repo }

# 4. What the server needs outside Python
Step "external services"
$tesseract = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $tesseract -and -not (Test-Path "$env:ProgramFiles\Tesseract-OCR\tesseract.exe")) {
    Warn "Tesseract not found: scanned PDFs will be indexed without OCR (set TESSERACT_CMD or install it)"
}
try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://localhost:13305/api/v1/models" | Out-Null
} catch {
    Warn "Lemonade is not answering on localhost:13305 - start it, or change lemonade.base_url in config.yaml"
}

# 5. Optional watcher at logon
if ($Daemon) {
    Step "Task Scheduler: Flying_RAG_MCP_Daemon"
    $run = "`"$VenvPy`" `"$(Join-Path $Repo 'main.py')`" --daemon"
    if ($HomeDir) { $run = "cmd /c set FLYING_RAG_HOME=$resolvedHome&& $run" }
    schtasks /create /tn "Flying_RAG_MCP_Daemon" /tr $run /sc onlogon /f | Out-Null
    if ($LASTEXITCODE -ne 0) { Warn "task registration failed" }
}

Write-Host ""
Write-Host "Done. Config: $(Join-Path $resolvedHome 'config.yaml')" -ForegroundColor Green
Write-Host "Add this to the mcpServers section of the MCP client"
Write-Host "(Claude Desktop: %APPDATA%\Claude\claude_desktop_config.json):"
Write-Host ""
$entry | ForEach-Object { Write-Host $_ }
