# usage: midiring.ps1 [-Count 2..4] [-Prg run\gauntlet\GAUNTLET.PRG] [-Port 5001] [-Seconds 0] [-Extra "--option"]
# Starts Count Hatari instances (the F030Arcade build, with --midi-net-in / --midi-net-out: src/midinet.c) cabled as
# a MIDI ring, MIDI-Maze style: instance k's MIDI OUT goes to instance k+1's MIDI IN, the last one's to the first's.
# Each instance runs the program from a folder of its own (run\midiring\<k>\: its GEMDOS drive C:) with its own log.
# -Seconds > 0: stops them all after that long; else they run until closed.
# F030ARCADE (default C:\Arbeit\F030Arcade) and MSYS2 (default C:\msys64) override the tool locations.
param([int]$Count = 2, [string]$Prg = "run\gauntlet\GAUNTLET.PRG", [int]$Port = 5001, [int]$Seconds = 0,
      [string[]]$Extra = @())
$ErrorActionPreference = "Stop"
if ($Count -lt 2 -or $Count -gt 4) { throw "Count: 2 to 4 machines" }
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:\Arbeit\F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:\msys64" }
$env:PATH = "$msys\ucrt64\bin;$msys\usr\bin;" + $env:PATH
$h = "$arcade\third_party\hatari\build-ucrt64\src\hatari.exe"
$tos = "$arcade\third_party\tos\tos206de.img"
$src = if ([IO.Path]::IsPathRooted($Prg)) { $Prg } else { Join-Path $root $Prg }
$name = Split-Path $src -Leaf
$procs = @()
for ($k = 0; $k -lt $Count; $k++) {
    $dir = Join-Path $root "run\midiring\$k"
    New-Item -ItemType Directory -Force $dir | Out-Null
    Copy-Item $src $dir -Force
    $in = $Port + $k
    $out = "127.0.0.1:" + ($Port + (($k + 1) % $Count))
    $cargs = @("--machine", "ste", "--memsize", "4", "--tos", $tos, "--fast-boot", "true", "--cpu-exact", "true",
               "--compatible", "true", "--confirm-quit", "off", "--statusbar", "false", "--borders", "true",
               "--log-file", "$dir\hatari.log", "--midi-net-in", "$in", "--midi-net-out", $out) + $Extra +
             @("$dir\$name")
    $procs += Start-Process -FilePath $h -WorkingDirectory $dir -ArgumentList $cargs -PassThru
    "machine $k : MIDI IN :$in, MIDI OUT $out ($dir)"
}
if ($Seconds -gt 0) {
    Start-Sleep -Seconds $Seconds
    $procs | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}
