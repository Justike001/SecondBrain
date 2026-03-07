param(
  [Parameter(Mandatory = $true, Position = 0)]
  [string]$Url
)

$ErrorActionPreference = "Stop"

function Get-QueryParam {
  param(
    [Parameter(Mandatory = $true)]
    [uri]$Uri,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  $query = $Uri.Query.TrimStart("?")
  if ([string]::IsNullOrWhiteSpace($query)) {
    return $null
  }

  foreach ($pair in $query.Split("&", [System.StringSplitOptions]::RemoveEmptyEntries)) {
    $kv = $pair.Split("=", 2)
    if ($kv.Count -ge 1 -and $kv[0] -eq $Name) {
      if ($kv.Count -eq 2) {
        return [uri]::UnescapeDataString($kv[1])
      }
      return ""
    }
  }
  return $null
}

function Resolve-ShortUrl {
  param(
    [Parameter(Mandatory = $true)]
    [string]$InputUrl
  )
  try {
    $resp = Invoke-WebRequest -Uri $InputUrl -MaximumRedirection 5 -Method Head -ErrorAction Stop
    $final = $resp.BaseResponse.ResponseUri.AbsoluteUri
    if (-not [string]::IsNullOrWhiteSpace($final)) {
      return $final
    }
  } catch {
    # Keep original URL when redirect probing is blocked.
  }
  return $InputUrl
}

function Fetch-RJina {
  param(
    [Parameter(Mandatory = $true)]
    [string]$TargetUrl
  )
  $readerUrl = "https://r.jina.ai/$TargetUrl"
  $content = (& curl.exe -L -sS $readerUrl -H "Accept: text/markdown" 2>&1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($content)) {
    throw "r.jina.ai fetch failed for $TargetUrl"
  }
  return $content
}

function Emit-LoginMarkdown {
  param(
    [Parameter(Mandatory = $true)]
    [string]$TargetUrl,
    [Parameter(Mandatory = $true)]
    [string]$DetailMessage
  )

  $qrPath = Join-Path $env:TEMP "xiaohongshu-login-qr.png"
  try {
    $qrRaw = (& mcporter call xiaohongshu.get_login_qrcode --output raw 2>&1 | Out-String)
    $m = [regex]::Match($qrRaw, "data:\s*'([^']+)'")
    if ($m.Success) {
      $bytes = [Convert]::FromBase64String($m.Groups[1].Value)
      [System.IO.File]::WriteAllBytes($qrPath, $bytes)
    }
  } catch {
    # Best effort only.
  }

  @"
# Xiaohongshu Login Required

- URL: $TargetUrl
- QR image (if generated): $qrPath

$DetailMessage
"@
}

$normalizedUrl = $Url.Trim()
if ([string]::IsNullOrWhiteSpace($normalizedUrl)) {
  throw "URL is empty."
}

$normalizedUrl = Resolve-ShortUrl -InputUrl $normalizedUrl
[uri]$uri = $normalizedUrl
$urlHost = $uri.Host.ToLowerInvariant()
$isXhs = $urlHost -match "(^|\.)xiaohongshu\.com$"

if (-not $isXhs) {
  Fetch-RJina -TargetUrl $normalizedUrl
  exit 0
}

$feedId = $null
$path = $uri.AbsolutePath
if ($path -match "/explore/([^/?#]+)") {
  $feedId = $Matches[1]
} elseif ($path -match "/discovery/item/([^/?#]+)") {
  $feedId = $Matches[1]
}
$xsecToken = Get-QueryParam -Uri $uri -Name "xsec_token"

if ([string]::IsNullOrWhiteSpace($feedId) -or [string]::IsNullOrWhiteSpace($xsecToken)) {
  @"
# Xiaohongshu URL Parse Failed

- URL: $normalizedUrl
- feed_id: $feedId
- xsec_token: $xsecToken

Expected URL pattern:
- https://www.xiaohongshu.com/explore/<feed_id>?xsec_token=<token>&...
"@
  exit 0
}

$detail = (& mcporter call xiaohongshu.get_feed_detail "feed_id=$feedId" "xsec_token=$xsecToken" --output markdown 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
  throw "mcporter xiaohongshu.get_feed_detail failed: $detail"
}

if ($detail -match "未登录|login status|扫码登录|not logged") {
  Emit-LoginMarkdown -TargetUrl $normalizedUrl -DetailMessage $detail
  exit 0
}

@"
# Xiaohongshu Note Extract

- URL: $normalizedUrl
- feed_id: $feedId

$detail
"@
