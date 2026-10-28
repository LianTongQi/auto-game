param(
    [ValidateSet('Ocr','DismissNews','StartDaily')][string]$Action,
    [string]$ImagePath='',
    [int]$OwnedPid=0,
    [string]$Language='zh-Hans-CN'
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
if($Action -ne 'Ocr'){
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
    $window=@($windows | Where-Object {$_.Current.ProcessId -eq $OwnedPid -and $_.Current.Name -like 'MaaEnd*'})
    if($window.Count -ne 1){throw 'Owned MaaEnd window not unique'}
    $buttons=@($window[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and $_.Current.IsEnabled})
    if($Action -eq 'StartDaily' -and @($buttons | Where-Object {$_.Current.Name -match '^停止(任务)?'}).Count){'ALREADY_RUNNING';exit 0}
    $selected=@($buttons | Where-Object {if($Action -eq 'DismissNews'){$_.Current.Name -eq '我知道了'}else{$_.Current.Name -match '^开始(?:任务|执行|运行)?(?:\s*[（(]?F10[）)]?)?$'}})
    if($Action -eq 'DismissNews' -and $selected.Count -eq 0){'NEWS_NOT_PRESENT';exit 0}
    if($selected.Count -ne 1){throw 'Safe named MaaEnd button not unique'}
    if($Action -eq 'StartDaily'){
        $currentName=$selected[0].Current.Name
        if($currentName -match '^停止(任务)?'){'ALREADY_RUNNING';exit 0}
        if($currentName -notmatch '^开始(?:任务|执行|运行)?(?:\s*[（(]?F10[）)]?)?$'){throw 'MaaEnd button changed before invocation'}
    }
    $selected[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    'INVOKED';exit 0
}
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
$asTask=@([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'})[0]
function Await($operation,[Type]$resultType){
    $task=$asTask.MakeGenericMethod($resultType).Invoke($null,@($operation))
    try{if(-not $task.Wait(10000)){throw 'Windows OCR operation timed out'}}
    catch{if($task.Exception){throw ('Windows OCR: '+$task.Exception.GetBaseException().Message)};throw}
    return $task.Result
}
$file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try{
    $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language($Language)))
    if(-not $engine){$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()}
    if(-not $engine){throw 'Install a Windows OCR language pack before using automatic official-launcher startup'}
    $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines=@($result.Lines | ForEach-Object {
        $words=@($_.Words)
        if($words.Count){
            $left=($words | ForEach-Object {$_.BoundingRect.X} | Measure-Object -Minimum).Minimum
            $top=($words | ForEach-Object {$_.BoundingRect.Y} | Measure-Object -Minimum).Minimum
            $right=($words | ForEach-Object {$_.BoundingRect.X+$_.BoundingRect.Width} | Measure-Object -Maximum).Maximum
            $bottom=($words | ForEach-Object {$_.BoundingRect.Y+$_.BoundingRect.Height} | Measure-Object -Maximum).Maximum
            [pscustomobject]@{text=$_.Text;x=$left;y=$top;width=$right-$left;height=$bottom-$top}
        }
    })
    ConvertTo-Json -InputObject $lines -Compress -Depth 4
}finally{$stream.Dispose()}
