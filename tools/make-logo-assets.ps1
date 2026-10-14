# Turns a black-on-white logo image into the launcher's assets:
#   launcher\assets\logo.png  256x256, transparent background, figures recolored for the dark UI
#   launcher\assets\logo.ico  16-256 px icon for the exe and window
# usage: .\tools\make-logo-assets.ps1 path\to\source.png [-Color "#E8E4F0"]
param(
    [Parameter(Mandatory)] [string] $Source,
    [string] $Color = "#E8E4F0"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$assets = Join-Path $PSScriptRoot "..\launcher\assets"
New-Item -ItemType Directory -Force $assets | Out-Null
$tint = [System.Drawing.ColorTranslator]::FromHtml($Color)

# Darkness becomes opacity: white turns transparent, black turns fully opaque in the tint color.
$src = New-Object System.Drawing.Bitmap $Source
$keyed = New-Object System.Drawing.Bitmap $src.Width, $src.Height, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$minX = $src.Width; $minY = $src.Height; $maxX = 0; $maxY = 0
for ($y = 0; $y -lt $src.Height; $y++) {
    for ($x = 0; $x -lt $src.Width; $x++) {
        $p = $src.GetPixel($x, $y)
        $alpha = [Math]::Max(0, [Math]::Min(255, 255 - [int](($p.R + $p.G + $p.B) / 3)))
        if ($alpha -lt 24) { $alpha = 0 }
        $keyed.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($alpha, $tint.R, $tint.G, $tint.B))
        if ($alpha -gt 0) { $minX = [Math]::Min($minX, $x); $maxX = [Math]::Max($maxX, $x); $minY = [Math]::Min($minY, $y); $maxY = [Math]::Max($maxY, $y) }
    }
}
$src.Dispose()

# Trim to the figures, then center them on a square canvas with a small margin.
$w = $maxX - $minX + 1; $h = $maxY - $minY + 1
$side = [int]([Math]::Max($w, $h) * 1.08)
function New-Square([int] $size) {
    $bmp = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = "HighQualityBicubic"; $g.SmoothingMode = "HighQuality"; $g.PixelOffsetMode = "HighQuality"
    $scale = $size / $side
    $dest = New-Object System.Drawing.RectangleF ((($side - $w) / 2) * $scale), ((($side - $h) / 2) * $scale), ($w * $scale), ($h * $scale)
    $g.DrawImage($keyed, $dest, (New-Object System.Drawing.RectangleF $minX, $minY, $w, $h), [System.Drawing.GraphicsUnit]::Pixel)
    $g.Dispose()
    return $bmp
}

$png = New-Square 256
$png.Save((Join-Path $assets "logo.png"), [System.Drawing.Imaging.ImageFormat]::Png)

# ICO with PNG-compressed entries (supported since Windows Vista).
$sizes = 16, 24, 32, 48, 64, 128, 256
$images = foreach ($s in $sizes) {
    $bmp = New-Square $s; $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    , $ms.ToArray()
}
$ico = New-Object System.IO.MemoryStream; $bw = New-Object System.IO.BinaryWriter $ico
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]; $dim = if ($s -ge 256) { 0 } else { $s }
    $bw.Write([byte]$dim); $bw.Write([byte]$dim); $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([uint16]1); $bw.Write([uint16]32); $bw.Write([uint32]$images[$i].Length); $bw.Write([uint32]$offset)
    $offset += $images[$i].Length
}
foreach ($img in $images) { $bw.Write($img) }
[System.IO.File]::WriteAllBytes((Join-Path $assets "logo.ico"), $ico.ToArray())
$keyed.Dispose(); $png.Dispose()
Write-Host "Wrote logo.png and logo.ico to $assets"
