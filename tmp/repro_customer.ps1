$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:5275/api'
$login = Invoke-RestMethod -Method Post -ContentType 'application/json' -Body '{"username":"admin","password":"admin123"}' "$base/auth/login"
$token = $login.access_token
$headers = @{ Authorization = "Bearer $token" }
function AskStream($question, $conversationId=$null) {
  $bodyObj = @{ question = $question }
  if ($conversationId) { $bodyObj.conversation_id = $conversationId }
  $body = $bodyObj | ConvertTo-Json -Compress
  $resp = Invoke-WebRequest -Method Post -Headers $headers -ContentType 'application/json' -Body $body "$base/customer-service/ask-stream" -TimeoutSec 180
  $events = @()
  $blocks = [regex]::Split($resp.Content.Trim(), "\r?\n\r?\n")
  foreach ($block in $blocks) {
    if (-not $block.Trim()) { continue }
    $event = ''
    $dataLines = @()
    foreach ($line in [regex]::Split($block, "\r?\n")) {
      if ($line.StartsWith('event:')) { $event = $line.Substring(6).Trim() }
      elseif ($line.StartsWith('data:')) { $dataLines += $line.Substring(5).Trim() }
    }
    $dataText = ($dataLines -join "`n")
    $data = $null
    if ($dataText) { try { $data = $dataText | ConvertFrom-Json -Depth 100 } catch { $data = $dataText } }
    $events += [pscustomobject]@{ event=$event; data=$data }
  }
  return $events
}
function EventText($events) {
  $parts = @()
  foreach ($e in $events) {
    if ($e.event -eq 'content' -and $e.data.content) { $parts += [string]$e.data.content }
    elseif ($e.event -eq 'answer_delta' -and $e.data.text) { $parts += [string]$e.data.text }
  }
  return ($parts -join '')
}
$ev1 = AskStream '风暴炉pro-汽炉版的主要卖点是什么'
"ROUND1_EVENTS=" + (($ev1 | ForEach-Object {$_.event}) -join ',')
$meta1 = ($ev1 | Where-Object {$_.event -eq 'meta'} | Select-Object -Last 1).data
$trace1 = ($ev1 | Where-Object {$_.event -eq 'trace'} | Select-Object -Last 1).data
"ROUND1_CONVERSATION=$($meta1.conversation_id)"
"ROUND1_ANSWER=$(EventText $ev1)"
"ROUND1_META=" + ($meta1 | ConvertTo-Json -Depth 100 -Compress)
"ROUND1_TRACE=" + ($trace1 | ConvertTo-Json -Depth 50 -Compress)
$cid = $meta1.conversation_id
$ev2 = AskStream '他该如何清洗保养' $cid
"ROUND2_EVENTS=" + (($ev2 | ForEach-Object {$_.event}) -join ',')
$meta2 = ($ev2 | Where-Object {$_.event -eq 'meta'} | Select-Object -Last 1).data
$trace2 = ($ev2 | Where-Object {$_.event -eq 'trace'} | Select-Object -Last 1).data
"ROUND2_CONVERSATION=$($meta2.conversation_id)"
"ROUND2_ANSWER=$(EventText $ev2)"
"ROUND2_META=" + ($meta2 | ConvertTo-Json -Depth 100 -Compress)
"ROUND2_TRACE=" + ($trace2 | ConvertTo-Json -Depth 50 -Compress)
