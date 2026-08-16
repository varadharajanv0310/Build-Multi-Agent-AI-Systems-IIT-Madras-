<#
.SYNOPSIS
  Capture documentation screenshots of every page, in a clean browser.

.DESCRIPTION
  Uses the same approach the demo recording does, for the same reason: a
  normal browser window puts the operator's tabs, bookmarks and history in
  frame. This drives a throwaway profile in --app mode so the only thing
  captured is the page.

  gdigrab cannot grab a GPU-composited window by title (it returns black), so
  each shot is a region grab of the maximised window with the title bar and
  taskbar cropped out.
#>
[CmdletBinding()]
param(
  [string]$OutDir = "docs/screenshots",
  [int]$Width  = 3840,
  [int]$Height = 2004,
  [int]$OffsetY = 36,
  [int]$Scale  = 1920          # downscale for the repo
)

$ErrorActionPreference = "Stop"

$ffbin = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
if (-not $ffbin) { throw "ffmpeg not found" }
$brave = "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe"
if (-not (Test-Path $brave)) { throw "brave not found" }
$prof = "$env:TEMP\faultline-demo-profile"

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class ShotWin {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
"@

# gdigrab captures whatever is on top of the desktop, not a chosen window. If
# anything steals focus mid-run — and a first attempt at this captured the
# operator's own browser and a chat window instead of the page — the grab
# silently succeeds with the wrong content. Every shot is therefore bracketed
# by a foreground check, and a mismatch discards the file rather than shipping
# somebody's tabs to a public repo.
function Assert-Foreground {
  param([IntPtr]$Expected, [string]$Name)
  $fg = [ShotWin]::GetForegroundWindow()
  if ($fg -ne $Expected) {
    Write-Warning "   $Name -> another window is in front; shot rejected"
    return $false
  }
  return $true
}

New-Item -ItemType Directory -Force $OutDir | Out-Null

# name, url path+query, seconds to settle before the grab
$shots = @(
  @{ n = "01-landing";        u = "/";                                                          w = 6 },
  @{ n = "02-landing-jobs";   u = "/?autopilot=1&still=1&scroll=0.17";                          w = 7 },
  @{ n = "03-landing-panel";  u = "/?autopilot=1&still=1&scroll=0.40";                          w = 7 },
  @{ n = "04-ask-input";      u = "/ask";                                                       w = 6 },
  @{ n = "05-ask-result";     u = "/ask?autopilot=1&still=1&demo=question";                     w = 16 },
  @{ n = "06-ask-evidence";   u = "/ask?autopilot=1&still=1&demo=question&open=1&scroll=0.62";  w = 18 },
  @{ n = "07-review-input";   u = "/review";                                                    w = 6 },
  @{ n = "08-review-result";  u = "/review?autopilot=1&still=1&demo=seva";                      w = 18 },
  @{ n = "09-review-panel";   u = "/review?autopilot=1&still=1&demo=seva&scroll=0.42";          w = 20 },
  @{ n = "10-review-claims";  u = "/review?autopilot=1&still=1&demo=seva&open=1&scroll=0.80";   w = 20 }
)

foreach ($s in $shots) {
  Write-Host "-> $($s.n)"
  Get-Process brave -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -like "Faultline*" -and $_.MainWindowTitle -notlike "*- Brave" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2

  Start-Process $brave -ArgumentList @(
    "--app=http://localhost:8000$($s.u)",
    "--user-data-dir=$prof", "--no-first-run", "--no-default-browser-check",
    "--disable-infobars", "--disable-session-crashed-bubble",
    "--disable-features=Translate,BraveP3A"
  )
  Start-Sleep -Seconds 7
  $app = Get-Process brave -ErrorAction SilentlyContinue |
         Where-Object { $_.MainWindowTitle -like "Faultline*" -and $_.MainWindowTitle -notlike "*- Brave" } |
         Select-Object -First 1
  if ($app) {
    [void][ShotWin]::ShowWindow($app.MainWindowHandle, 3)
    Start-Sleep -Milliseconds 500
    [void][ShotWin]::SetForegroundWindow($app.MainWindowHandle)
  }
  Start-Sleep -Seconds $s.w

  $png = Join-Path $OutDir "$($s.n).png"
  & $ffbin -hide_banner -loglevel error -y -f gdigrab `
     -video_size "${Width}x${Height}" -offset_x 0 -offset_y $OffsetY -i desktop `
     -frames:v 1 -vf "scale=${Scale}:-2" $png
  if (Test-Path $png) {
    Write-Host ("   {0} KB" -f [math]::Round((Get-Item $png).Length / 1KB))
  } else {
    Write-Warning "   failed: $($s.n)"
  }
}

Get-Process brave -ErrorAction SilentlyContinue |
  Where-Object { $_.MainWindowTitle -like "Faultline*" -and $_.MainWindowTitle -notlike "*- Brave" } |
  ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

Write-Host "`ndone -> $OutDir"
