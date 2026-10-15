param(
    [Parameter(Mandatory=$true)][string]$VideoPath,
    [Parameter(Mandatory=$true)][string]$Out
)
$ErrorActionPreference = 'Stop'
$videoItem = Get-Item -LiteralPath $VideoPath
if (Test-Path -LiteralPath $Out) {
    if (Get-ChildItem -LiteralPath $Out -Force | Select-Object -First 1) { throw 'Fresh or empty output directory required' }
} else { New-Item -ItemType Directory -Path $Out | Out-Null }
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.FileProperties.VideoProperties,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Editing.MediaClip,Windows.Media.Editing,ContentType=WindowsRuntime] | Out-Null
$awaitMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Wait-MediaResult($Operation, [Type]$ResultType) {
    $task = $awaitMethod.MakeGenericMethod($ResultType).Invoke($null,@($Operation))
    if (-not $task.Wait(15000)) { throw 'Native media operation timeout (15s)' }
    return $task.Result
}
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$file = Wait-MediaResult ([Windows.Storage.StorageFile]::GetFileFromPathAsync($videoItem.FullName)) ([Windows.Storage.StorageFile])
$properties = Wait-MediaResult ($file.Properties.GetVideoPropertiesAsync()) ([Windows.Storage.FileProperties.VideoProperties])
$clip = Wait-MediaResult ([Windows.Media.Editing.MediaClip]::CreateFromFileAsync($file)) ([Windows.Media.Editing.MediaClip])
$encoding = $clip.GetVideoEncodingProperties()
$report = @{
    source=@{ path=$videoItem.FullName; bytes=$videoItem.Length; last_write_utc=$videoItem.LastWriteTimeUtc.ToString('o'); full_sha256=$null;
        full_sha256_reason='bounded inspection; no complete 3GB read'; synchronization='UNVERIFIED'; filename_clock_semantics='UNVERIFIED' };
    metadata=@{ width=$encoding.Width; height=$encoding.Height; duration_s=$clip.OriginalDuration.TotalSeconds;
        property_duration_s=$properties.Duration.TotalSeconds; codec=$encoding.Subtype;
        frame_rate_numerator=$encoding.FrameRate.Numerator; frame_rate_denominator=$encoding.FrameRate.Denominator;
        bitrate=$encoding.Bitrate; provider='Windows native media APIs' };
    runtime_s=$watch.Elapsed.TotalSeconds; inference_runs=0;
    limits=@{ native_operation_timeout_s=15 };
    interpretation='native media metadata only; no world-clock synchronization or lamp truth established'
}
$json = $report | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText((Join-Path $Out 'metadata.json'),$json,[System.Text.UTF8Encoding]::new($false))
$json
