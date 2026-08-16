<#
.SYNOPSIS
  Screen-capture a Faultline demo and mux narration onto it.

.DESCRIPTION
  Tested findings this script is built around:

    * gdigrab CANNOT capture a window by title when that window is
      GPU-composited (Chromium/Electron). It returns correctly-sized frames
      that are pure black — measured YAVG 16.0 vs 36.3 for a working grab.
      So we capture a REGION of the desktop, never "title=".

    * Because it is a desktop region, anything overlapping that rectangle ends
      up in the recording. Close or move anything private BEFORE recording.
      Verify with -Preview first.

  Steps are separable so a bad take only costs you that step.

.EXAMPLE
  # 0. See exactly what will be recorded, without recording
  .\scripts\capture_demo.ps1 -Preview

  # 1. Record 150 seconds of the top-left 1920x1080
  .\scripts\capture_demo.ps1 -Record -Duration 150

  # 2. Turn a script into narration (needs ELEVENLABS_API_KEY)
  .\scripts\capture_demo.ps1 -Narrate -ScriptFile demo\narration.txt

  # 3. Mux them into the final 1080p deliverable
  .\scripts\capture_demo.ps1 -Mux
#>
[CmdletBinding()]
param(
  [switch]$Preview,
  [switch]$Record,
  [switch]$Narrate,
  [switch]$Mux,

  [int]$Duration   = 150,
  [int]$Width      = 1920,
  [int]$Height     = 1080,
  [int]$OffsetX    = 0,
  [int]$OffsetY    = 0,
  [int]$Framerate  = 15,

  [string]$OutDir     = "demo\recording",
  [string]$ScriptFile = "demo\narration.txt",
  [string]$VoiceId    = "JBFqnCBsd6RMkjVDRZzb",   # "George" — calm, neutral
  [string]$ModelId    = "eleven_multilingual_v2"
)

$ErrorActionPreference = "Stop"

function Get-Ffmpeg {
  $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse `
             -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($found) { return $found.FullName }
  throw "ffmpeg not found. Install with:  winget install Gyan.FFmpeg"
}

# ffmpeg writes its analysis to stderr. Redirecting that inline with 2>&1 makes
# PowerShell 5.1 wrap every line in a NativeCommandError and fail the step even
# on exit 0, so stderr goes to a temp file and is read back as plain text.
function Invoke-FfmpegStderr {
  param([string[]]$FfArgs)
  $tmp = [System.IO.Path]::GetTempFileName()
  try {
    $p = Start-Process -FilePath $ffmpeg -ArgumentList $FfArgs -NoNewWindow `
           -Wait -PassThru -RedirectStandardError $tmp
    return Get-Content $tmp -ErrorAction SilentlyContinue
  } finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

$ffmpeg  = Get-Ffmpeg
$ffprobe = Join-Path (Split-Path $ffmpeg) "ffprobe.exe"
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force $OutDir | Out-Null }

$rawPath   = Join-Path $OutDir "capture.mp4"
$voicePath = Join-Path $OutDir "narration.mp3"
$finalPath = Join-Path $OutDir "faultline-demo.mp4"

# --- preview -----------------------------------------------------------------
# One frame of exactly what -Record would capture. Look at it before recording:
# this is the check that keeps a stray window out of the final video.
if ($Preview) {
  $shot = Join-Path $OutDir "preview.png"
  & $ffmpeg -hide_banner -loglevel error -y -f gdigrab `
      -video_size "${Width}x${Height}" -offset_x $OffsetX -offset_y $OffsetY `
      -i desktop -frames:v 1 $shot
  if ($LASTEXITCODE -ne 0) { throw "preview capture failed" }

  # Mean luminance: ~0 means the region is black (wrong monitor, or a
  # GPU-composited window that gdigrab cannot see).
  $lumArgs = @("-hide_banner", "-i", $shot, "-vf",
               "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "NUL")
  $stats = Invoke-FfmpegStderr $lumArgs | Select-String "YAVG" | Select-Object -First 1
  Write-Host "preview written : $shot"
  Write-Host "region          : ${Width}x${Height} at +$OffsetX,+$OffsetY"
  if ($stats) { Write-Host "luminance       : $($stats.Line -replace '.*YAVG=','YAVG=')" }
  Write-Host ""
  Write-Host "Open it. If it is black, the region is wrong or the window is GPU-composited."
  Write-Host "If anything private is visible, move it before recording."
  return
}

# --- record ------------------------------------------------------------------
if ($Record) {
  Write-Host "recording ${Duration}s of ${Width}x${Height} at +$OffsetX,+$OffsetY"
  Write-Host "starting in 5s - bring the demo window forward now..."
  Start-Sleep -Seconds 5

  & $ffmpeg -hide_banner -loglevel error -y -f gdigrab `
      -framerate $Framerate -video_size "${Width}x${Height}" `
      -offset_x $OffsetX -offset_y $OffsetY -t $Duration -i desktop `
      -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p $rawPath
  if ($LASTEXITCODE -ne 0) { throw "capture failed" }

  & $ffprobe -v error -select_streams v:0 `
      -show_entries stream=width,height,nb_frames -show_entries format=duration,size `
      -of default=noprint_wrappers=1 $rawPath

  # A frozen capture usually means the demo never actually rendered on screen.
  $freezeArgs = @("-hide_banner", "-i", $rawPath, "-vf",
                  "freezedetect=n=-60dB:d=3", "-f", "null", "NUL")
  $frozen = Invoke-FfmpegStderr $freezeArgs | Select-String "freeze_start"
  if ($frozen) {
    Write-Warning "Frozen segments detected - the screen may not have been updating:"
    $frozen | ForEach-Object { Write-Warning "  $($_.Line)" }
  } else {
    Write-Host "no frozen segments - screen changed throughout" -ForegroundColor Green
  }
  Write-Host "saved: $rawPath"
  return
}

# --- narrate -----------------------------------------------------------------
if ($Narrate) {
  $key = $env:ELEVENLABS_API_KEY
  if (-not $key) {
    # Fall back to the project's .env so the key lives in one place.
    if (Test-Path ".env") {
      $line = Get-Content ".env" | Where-Object { $_ -match "^\s*ELEVENLABS_API_KEY\s*=" } | Select-Object -First 1
      if ($line) { $key = ($line -split "=", 2)[1].Trim() }
    }
  }
  if (-not $key) { throw "ELEVENLABS_API_KEY not set (env var or .env)" }
  if (-not (Test-Path $ScriptFile)) { throw "narration script not found: $ScriptFile" }

  $text = (Get-Content $ScriptFile -Raw).Trim()
  if (-not $text) { throw "narration script is empty" }
  Write-Host "synthesising $($text.Length) characters with voice $VoiceId"

  $body = @{
    text     = $text
    model_id = $ModelId
    voice_settings = @{ stability = 0.5; similarity_boost = 0.75; speed = 0.95 }
  } | ConvertTo-Json -Depth 5

  $uri = "https://api.elevenlabs.io/v1/text-to-speech/$VoiceId"
  Invoke-RestMethod -Uri $uri -Method Post -ContentType "application/json" `
    -Headers @{ "xi-api-key" = $key } `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -OutFile $voicePath

  if (-not (Test-Path $voicePath)) { throw "no audio returned" }
  $dur = & $ffprobe -v error -show_entries format=duration -of csv=p=0 $voicePath
  Write-Host "saved: $voicePath  ($([math]::Round([double]$dur,1))s)" -ForegroundColor Green
  Write-Host "Match this against your capture length before muxing."
  return
}

# --- mux ---------------------------------------------------------------------
if ($Mux) {
  if (-not (Test-Path $rawPath))   { throw "no capture at $rawPath - run -Record first" }
  if (-not (Test-Path $voicePath)) { throw "no narration at $voicePath - run -Narrate first" }

  $vDur = [double](& $ffprobe -v error -show_entries format=duration -of csv=p=0 $rawPath)
  $aDur = [double](& $ffprobe -v error -show_entries format=duration -of csv=p=0 $voicePath)
  Write-Host ("video {0:N1}s / audio {1:N1}s" -f $vDur, $aDur)
  if ([math]::Abs($vDur - $aDur) -gt 10) {
    Write-Warning "Tracks differ by more than 10s; -shortest will clip the longer one."
  }

  & $ffmpeg -hide_banner -loglevel error -y -i $rawPath -i $voicePath `
      -vf "scale=${Width}:${Height}:flags=lanczos" `
      -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p `
      -c:a aac -b:a 192k -shortest -movflags +faststart $finalPath
  if ($LASTEXITCODE -ne 0) { throw "mux failed" }

  & $ffprobe -v error -show_entries stream=codec_type,codec_name,width,height `
      -show_entries format=duration,size -of default=noprint_wrappers=1 $finalPath
  Write-Host "FINAL: $finalPath" -ForegroundColor Green
  return
}

Write-Host "Pick a step: -Preview | -Record | -Narrate | -Mux    (Get-Help .\scripts\capture_demo.ps1 -Full)"
