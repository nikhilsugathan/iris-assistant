param(
    [string]$Model = "base",
    [string]$Device = "cpu",
    [string]$ComputeType = "int8"
)

$script = @"
import subprocess
import sys

model = sys.argv[1] if len(sys.argv) > 1 else "base"
device = sys.argv[2] if len(sys.argv) > 2 else "cpu"
compute_type = sys.argv[3] if len(sys.argv) > 3 else "int8"

subprocess.check_call([sys.executable, "-m", "pip", "install", "faster-whisper"])

from faster_whisper import WhisperModel

WhisperModel(model, device=device, compute_type=compute_type)
print(f"Prepared faster-whisper model '{model}' ({device}, {compute_type}).")
"@

$script | python - $Model $Device $ComputeType
