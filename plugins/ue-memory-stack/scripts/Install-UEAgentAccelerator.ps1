<#
.SYNOPSIS
    Adds the plugin to an Unreal project and enables it in the .uproject.

.DESCRIPTION
    Two ways to do it, and which one you want depends on how many projects you're running this on.

    Copy      Copies the plugin into <Project>\Plugins. Simplest, and the right choice for one
              project. Each project ends up with its own copy of the source.
    Reference Leaves the plugin where it is and adds an AdditionalPluginDirectories entry pointing
              at its parent folder, so several projects share one copy of the source. Note the
              binaries are still built per project either way.

    Either way we add the plugin to the Plugins array with Enabled true, because a plugin that is
    on disk but not enabled is loaded by nothing and the dump reports zero modules.

    If the .uproject is under Perforce it is checked out before it is written. Read only files are
    the obvious reason for that, but not the interesting one: a descriptor of type +w stays writable
    whether or not it is open, so without the checkout the write succeeds and the change never joins
    a changelist. See Common.ps1 for the detail.

    The descriptor is edited as text rather than reserialised, so the diff is the few lines that
    changed and the file keeps its own indentation, line endings and byte order mark. Every edit is
    parsed back and compared against the original before it is written, and the descriptor is left
    alone entirely if it already says what we were going to make it say.

.EXAMPLE
    .\Install-UEAgentAccelerator.ps1 -ProjectPath D:\Game\Game.uproject
    .\Install-UEAgentAccelerator.ps1 -ProjectPath D:\Game\Game.uproject -Mode Reference
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $ProjectPath,

    [ValidateSet('Copy', 'Reference')]
    [string] $Mode = 'Copy',

    # Resolved in the body, not here: on Windows PowerShell 5.1 $PSScriptRoot is empty while
    # parameter defaults are evaluated, and Join-Path then refuses the empty string.
    [string] $PluginSource,

    # Overwrite an existing installed copy.
    [switch] $Force,

    # Don't touch Perforce. Clears the read only flag and writes anyway, so use it when you intend
    # to put the descriptor in a changelist yourself.
    [switch] $NoSourceControl
)

$ErrorActionPreference = 'Stop'

if (-not $PluginSource) {
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $PluginSource = Join-Path $here '..\ue-plugin\UEAgentAccelerator'
}

. (Join-Path $PSScriptRoot 'Common.ps1')

$PluginName = 'UEAgentAccelerator'

# ---------------------------------------------------------------------------------------------
# Descriptor editing.
#
# These work on the descriptor as text. Reserialising it through ConvertTo-Json is a one line
# change to Unreal and a whole file change to everybody else: PowerShell 5.1 reindents with four
# spaces, reorders keys, and Set-Content -Encoding UTF8 adds a byte order mark. On a real project
# that turned adding one plugin into a 2,292 line diff, which is unreviewable, resolves badly
# against anyone else's change to the same file, and hides whatever else was in the changelist.
# ---------------------------------------------------------------------------------------------

function Find-JsonMatch {
    <#
        Index of the bracket or brace closing the one at $Start. Strings and their escapes are
        skipped, so a path containing a brace doesn't throw the count out.
    #>
    param([Parameter(Mandatory)] [string] $Text, [Parameter(Mandatory)] [int] $Start)

    $open   = $Text[$Start]
    $close  = if ($open -eq '[') { ']' } else { '}' }
    $depth  = 0
    $inStr  = $false
    $escape = $false

    for ($i = $Start; $i -lt $Text.Length; $i++) {
        $c = $Text[$i]
        if ($escape)     { $escape = $false; continue }
        if ($c -eq '\')  { if ($inStr) { $escape = $true }; continue }
        if ($c -eq '"')  { $inStr = -not $inStr; continue }
        if ($inStr)      { continue }
        if     ($c -eq $open)  { $depth++ }
        elseif ($c -eq $close) { $depth--; if ($depth -eq 0) { return $i } }
    }
    return -1
}

function Get-JsonArrayElements {
    # Start and end index of each top level object in the array whose brackets are $Open..$Close.
    param([string] $Text, [int] $Open, [int] $Close)

    $elements = @()
    $i = $Open + 1
    while ($i -lt $Close) {
        if ($Text[$i] -eq '{') {
            $end = Find-JsonMatch $Text $i
            if ($end -lt 0 -or $end -gt $Close) { break }
            $elements += [pscustomobject]@{ Start = $i; End = $end }
            $i = $end + 1
            continue
        }
        $i++
    }
    return $elements
}

function Get-LineIndent {
    # The whitespace between the start of $Index's line and $Index.
    param([string] $Text, [int] $Index)

    $lineStart = $Text.LastIndexOf("`n", [Math]::Max($Index - 1, 0)) + 1
    $prefix    = $Text.Substring($lineStart, $Index - $lineStart)
    if ($prefix -match '^(\s*)') { return $Matches[1] }
    return ''
}

function Add-PluginToDescriptorText {
    <#
        Adds or enables the plugin entry, returning the new text, or $null if the surgical edit
        can't be done and the caller should fall back to reserialising.

        A new entry is appended in the style of the last one, tabs or spaces and one line or
        several, so it looks like the editor wrote it.
    #>
    param([Parameter(Mandatory)] [string] $Text, [Parameter(Mandatory)] [string] $Name)

    $m = [regex]::Match($Text, '"Plugins"\s*:\s*\[')
    if (-not $m.Success) {
        Write-Verbose "No Plugins array in the descriptor."
        return $null
    }

    $open  = $m.Index + $m.Length - 1
    $close = Find-JsonMatch $Text $open
    if ($close -lt 0) { return $null }

    $elements = Get-JsonArrayElements $Text $open $close

    # Already listed? Then all we might need is Enabled flipped to true.
    foreach ($e in $elements) {
        $entry = $Text.Substring($e.Start, $e.End - $e.Start + 1)
        if ($entry -notmatch '"Name"\s*:\s*"' + [regex]::Escape($Name) + '"') { continue }

        if ($entry -match '"Enabled"\s*:\s*true') { return $Text }
        if ($entry -match '"Enabled"\s*:\s*false') {
            $fixed = [regex]::Replace($entry, '("Enabled"\s*:\s*)false', '${1}true', 1)
            return $Text.Remove($e.Start, $entry.Length).Insert($e.Start, $fixed)
        }
        # Listed with no Enabled key at all. Rare, and adding one means guessing where in the
        # object it goes, so hand it back to the reserialiser.
        Write-Verbose "Plugin is listed with no Enabled key."
        return $null
    }

    # An empty array gives us no house style to copy and no element to append after, so that one
    # goes to the reserialiser too.
    if ($elements.Count -eq 0) {
        Write-Verbose "Plugins array is empty."
        return $null
    }

    $last      = $elements[-1]
    $lastText  = $Text.Substring($last.Start, $last.End - $last.Start + 1)
    $indent    = Get-LineIndent $Text $last.Start
    $newline   = if ($Text -match "`r`n") { "`r`n" } else { "`n" }

    if ($lastText -match "`n") {
        # Multi line entries. Take the inner indent from the entry we're copying rather than
        # guessing a unit, so a file indented with tabs stays indented with tabs.
        $inner = Get-LineIndent $Text ($Text.IndexOf('"', $last.Start))
        $entry = "{$newline$inner`"Name`": `"$Name`",$newline$inner`"Enabled`": true$newline$indent}"
    }
    else {
        $entry = "{ `"Name`": `"$Name`", `"Enabled`": true }"
    }

    return $Text.Insert($last.End + 1, ",$newline$indent$entry")
}

function Add-PluginDirectoryToDescriptorText {
    <#
        Puts a path in AdditionalPluginDirectories, creating the whole key if the descriptor hasn't
        got one. Returns the text unchanged if the path is already listed, or $null if the edit
        can't be made.

        Creating the key matters more than it sounds. No project has this key before its first
        -Mode Reference install, so without it every Reference install fell through to reserialising
        the descriptor and Reference mode never got the small diff at all.
    #>
    param([Parameter(Mandatory)] [string] $Text, [Parameter(Mandatory)] [string] $Directory)

    # JSON escaping, so a Windows path compares as it will be written.
    $escaped = $Directory -replace '\\', '\\'
    $newline = if ($Text -match "`r`n") { "`r`n" } else { "`n" }

    $m = [regex]::Match($Text, '"AdditionalPluginDirectories"\s*:\s*\[')
    if ($m.Success) {
        $open  = $m.Index + $m.Length - 1
        $close = Find-JsonMatch $Text $open
        if ($close -lt 0) { return $null }

        $body = $Text.Substring($open + 1, $close - $open - 1)
        if ($body -match '"' + [regex]::Escape($escaped) + '"') { return $Text }

        $lastQuote = $body.LastIndexOf('"')
        if ($lastQuote -lt 0) { return $null }

        $at     = $open + 1 + $lastQuote + 1
        $indent = Get-LineIndent $Text ($open + 1 + $body.IndexOf('"'))
        return $Text.Insert($at, ",$newline$indent`"$escaped`"")
    }

    # No key yet, so write one in front of Plugins. That anchor is safe because we only get here
    # after the Plugins edit succeeded, which means the key exists.
    $p = [regex]::Match($Text, '"Plugins"\s*:\s*\[')
    if (-not $p.Success) { return $null }

    $indent = Get-LineIndent $Text $p.Index
    $inner  = $indent + (Get-IndentUnit $Text $indent)
    $block  = "`"AdditionalPluginDirectories`": [$newline$inner`"$escaped`"$newline$indent],$newline$indent"
    return $Text.Insert($p.Index, $block)
}

function Get-IndentUnit {
    <#
        One level of indentation as this file writes it, worked out by finding a line indented one
        step deeper than $Outer. Guessing a unit instead means a tab indented descriptor picks up
        spaces on the one line we add, which is the sort of thing that shows up in a review.
    #>
    param([string] $Text, [string] $Outer)

    $m = [regex]::Match($Text, "(?m)^$([regex]::Escape($Outer))(\t+| +)\S")
    if ($m.Success) { return $m.Groups[1].Value }
    if ($Outer -match '\t') { return "`t" }
    return '    '
}

function Assert-DescriptorUnharmed {
    <#
        The safety net under the text editing. Reparses both versions and insists that the only
        difference is the one we meant to make: same top level keys, same module list, and the
        plugin list changed by at most our own entry.
    #>
    param([Parameter(Mandatory)] [string] $Before, [Parameter(Mandatory)] [string] $After,
          [Parameter(Mandatory)] [string] $Name)

    $a = $Before | ConvertFrom-Json
    $b = $After  | ConvertFrom-Json

    # AdditionalPluginDirectories is the one key we're allowed to introduce, in Reference mode.
    $keysA = @($a.PSObject.Properties.Name)
    $keysB = @($b.PSObject.Properties.Name) | Where-Object {
        $_ -ne 'AdditionalPluginDirectories' -or $keysA -contains $_
    }
    if (($keysA -join ',') -ne ($keysB -join ',')) {
        throw "Descriptor edit changed the top level keys: '$($keysA -join ',')' became '$(@($b.PSObject.Properties.Name) -join ',')'."
    }

    if (@($a.Modules).Count -ne @($b.Modules).Count) {
        throw "Descriptor edit changed the module count from $(@($a.Modules).Count) to $(@($b.Modules).Count)."
    }

    $namesA = @($a.Plugins | ForEach-Object { $_.Name }) | Where-Object { $_ -ne $Name }
    $namesB = @($b.Plugins | ForEach-Object { $_.Name }) | Where-Object { $_ -ne $Name }
    if ((@($namesA) -join ',') -ne (@($namesB) -join ',')) {
        throw "Descriptor edit disturbed the other plugin entries."
    }

    $ours = @($b.Plugins | Where-Object { $_.Name -eq $Name })
    if ($ours.Count -ne 1)  { throw "Descriptor edit left $($ours.Count) entries for $Name, expected exactly one." }
    if (-not $ours[0].Enabled) { throw "Descriptor edit left $Name disabled." }
}

# ---------------------------------------------------------------------------------------------

$ProjectPath  = (Resolve-Path $ProjectPath).Path
$PluginSource = (Resolve-Path $PluginSource).Path
$projectDir   = Split-Path -Parent $ProjectPath
$pluginParent = Split-Path -Parent $PluginSource

if (-not (Test-Path (Join-Path $PluginSource "$PluginName.uplugin"))) {
    throw "No $PluginName.uplugin in $PluginSource."
}

$backup = "$ProjectPath.bak"

switch ($Mode) {
    'Copy' {
        $dest = Join-Path $projectDir "Plugins\$PluginName"
        if ((Test-Path $dest) -and -not $Force) {
            throw "$dest already exists. Pass -Force to overwrite it."
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }

        # Source and descriptor only. Binaries and Intermediate belong to whatever project built
        # them, so copying them across gives you a DLL built for a different target.
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item (Join-Path $PluginSource "$PluginName.uplugin") $dest
        Copy-Item (Join-Path $PluginSource 'Source') $dest -Recurse
        Write-Host "Copied plugin to $dest"
    }
    'Reference' {
        Write-Host "Referencing plugin directory $pluginParent"
    }
}

# Keep the bytes, not just the characters. ReadAllText strips a byte order mark silently, so
# without noting it here the file loses one it had, or gains one it didn't, on every install.
$bytes  = [IO.File]::ReadAllBytes($ProjectPath)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
$before = [IO.File]::ReadAllText($ProjectPath)

$after = Add-PluginToDescriptorText -Text $before -Name $PluginName

if ($after -and $Mode -eq 'Reference') {
    $withDir = Add-PluginDirectoryToDescriptorText -Text $after -Directory $pluginParent
    if ($null -eq $withDir) {
        Write-Verbose "No AdditionalPluginDirectories array to append to."
        $after = $null
    }
    else {
        $after = $withDir
    }
}

if ($after) {
    Assert-DescriptorUnharmed -Before $before -After $after -Name $PluginName
}
else {
    # Nothing here can be done as a text edit, so fall back to reserialising the whole descriptor.
    # It's correct, it's just noisy, hence the warning.
    Write-Warning "Rewriting the whole descriptor as JSON. Indentation and key order will change."
    $json = $before | ConvertFrom-Json
    if (-not $json.PSObject.Properties.Name.Contains('Plugins')) {
        $json | Add-Member -MemberType NoteProperty -Name 'Plugins' -Value @()
    }
    $existing = @($json.Plugins | Where-Object { $_.Name -eq $PluginName })
    if ($existing) {
        $existing[0].Enabled = $true
    } else {
        $json.Plugins = @($json.Plugins) + [pscustomobject]@{ Name = $PluginName; Enabled = $true }
    }
    if ($Mode -eq 'Reference') {
        if (-not $json.PSObject.Properties.Name.Contains('AdditionalPluginDirectories')) {
            $json | Add-Member -MemberType NoteProperty -Name 'AdditionalPluginDirectories' -Value @()
        }
        # The entry points at the folder that CONTAINS plugin folders, not at the plugin itself.
        if (@($json.AdditionalPluginDirectories) -notcontains $pluginParent) {
            $json.AdditionalPluginDirectories = @($json.AdditionalPluginDirectories) + $pluginParent
        }
    }
    $after = $json | ConvertTo-Json -Depth 20
}

if ($after -ceq $before) {
    Write-Host "Descriptor already enables $PluginName. Left alone."
}
else {
    # Back it up before touching it. It's small, and a broken .uproject is a bad afternoon.
    #
    # An existing backup is never overwritten. Running the installer twice used to replace the
    # pristine copy with the one it had just modified, so the second run quietly destroyed the only
    # way back to the descriptor as it was before any of this touched it.
    if (Test-Path $backup) {
        Write-Host "Keeping the existing backup at $backup"
    }
    else {
        Copy-Item $ProjectPath $backup -Force
        Write-Host "Backed up descriptor to $backup"
    }

    # Checked out here rather than at the top, so a run that changes nothing doesn't open a file for
    # a change it isn't going to make, and a run that fails earlier doesn't either.
    $how = Unlock-FileForWrite -Path $ProjectPath -NoSourceControl:$NoSourceControl
    Write-Host "Descriptor: $how"

    [IO.File]::WriteAllText($ProjectPath, $after, (New-Object Text.UTF8Encoding($hasBom)))
    Write-Host "Enabled $PluginName in $(Split-Path -Leaf $ProjectPath)"
}

Write-Host ""
Write-Host "Next: build the editor target, then run the dump."
Write-Host "  .\Build-UEAgentAccelerator.ps1 -ProjectPath $ProjectPath -EnginePath <engine root>"
Write-Host "  .\Invoke-AgentMemoryDump.ps1  -ProjectPath $ProjectPath -EnginePath <engine root>"
