$ErrorActionPreference = "Stop"

$pluginRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPath = if ($env:LOCAL_GPU_IMAGEGEN_VENV) { $env:LOCAL_GPU_IMAGEGEN_VENV } else { Join-Path $pluginRoot ".venv" }

function Resolve-ImagegenPython {
    if ($env:LOCAL_GPU_IMAGEGEN_PYTHON) {
        return @($env:LOCAL_GPU_IMAGEGEN_PYTHON)
    }

    $candidates = @(
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("python")
    )

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $args = @($candidate | Select-Object -Skip 1)
        try {
            $versionText = & $exe @args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            if ($LASTEXITCODE -eq 0 -and $versionText -match "^(3\.11|3\.12)$") {
                if ($args.Count -gt 0) {
                    return @($exe) + $args
                }
                return @($exe)
            }
        }
        catch {
        }
    }

    try {
        $pyList = & py -0p
        foreach ($line in $pyList) {
            if ($line -match "(?<path>[A-Za-z]:\\.*python(?:3\.\d+t?)?\.exe)$") {
                $path = $Matches["path"]
                try {
                    $versionText = & $path -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
                    if ($LASTEXITCODE -eq 0 -and $versionText -match "^(3\.11|3\.12)$") {
                        return @($path)
                    }
                }
                catch {
                }
            }
        }
    }
    catch {
    }

    throw "No supported Python found. Install Python 3.11/3.12 or set LOCAL_GPU_IMAGEGEN_PYTHON to a compatible python.exe. PyTorch CUDA wheels are not reliably available for Python 3.14/3.15."
}

function Invoke-ImagegenPython {
    param([string[]]$Arguments)
    $exe = $script:pythonCommand[0]
    $baseArgs = @($script:pythonCommand | Select-Object -Skip 1)
    & $exe @baseArgs @Arguments
}

function Initialize-ImagegenVenv {
    $basePython = @(Resolve-ImagegenPython)
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Creating virtual environment: $venvPath"
        $exe = $basePython[0]
        $baseArgs = @($basePython | Select-Object -Skip 1)
        & $exe @baseArgs -m venv $venvPath
    }
    return @($venvPython)
}

$script:pythonCommand = @(Initialize-ImagegenVenv)
$torchIndexUrl = if ($env:LOCAL_GPU_IMAGEGEN_TORCH_INDEX_URL) { $env:LOCAL_GPU_IMAGEGEN_TORCH_INDEX_URL } else { "https://download.pytorch.org/whl/cu128" }

Write-Host "Installing local GPU image generation dependencies..."
Write-Host "Using Python: $($script:pythonCommand -join ' ')"
Write-Host "Using PyTorch index: $torchIndexUrl"
Invoke-ImagegenPython @("-m", "pip", "install", "--upgrade", "pip")

# Install PyTorch with CUDA wheels. Override LOCAL_GPU_IMAGEGEN_TORCH_INDEX_URL if needed.
Invoke-ImagegenPython @("-m", "pip", "install", "--upgrade", "torch", "torchvision", "--index-url", $torchIndexUrl)
Invoke-ImagegenPython @("-m", "pip", "install", "--upgrade", "diffusers", "transformers", "accelerate", "safetensors", "pillow")

Write-Host "Checking GPU readiness..."
Invoke-ImagegenPython @("$pluginRoot\scripts\check_gpu.py")
