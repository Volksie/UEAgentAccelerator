<#
.SYNOPSIS
    Checks the PreToolUse write guard against the shapes a real session actually uses.

.DESCRIPTION
    Positives must be denied and negatives must pass, and the negatives are the half that decides
    whether the guard survives contact with people: one that blocks reading an artefact gets deleted by
    Friday, and then nothing is guarded.

    This exists because the guard's first version matched Write and Edit only, and the first person to
    test it bypassed it without trying - their session made file changes with sed, so the hook was never
    offered the call. Every shape below is one somebody has actually used.

    Run it after any change to hooks/Deny-ArtefactWrite.ps1.
#>
$ErrorActionPreference = 'Stop'
$hook = 'C:\ClaudeWork\UEAgentAccelerator\plugins\ue-memory-stack\hooks\Deny-ArtefactWrite.ps1'

function Ask($tool, $field, $value) {
    $payload = @{ tool_name = $tool; tool_input = @{ $field = $value } } | ConvertTo-Json -Compress -Depth 4
    $out = $payload | powershell -NoProfile -ExecutionPolicy Bypass -File $hook 2>&1
    return (($out -join '') -match 'permissionDecision.*deny')
}

$A = 'MyGame/Docs/AgentMemory/classes/UMyThing.md'
$cases = @(
    # --- must be denied -------------------------------------------------------------------------
    @{ Want = $true;  Tool = 'Edit'; Field = 'file_path'; V = "C:\g\$($A -replace '/','\')" ; Why = 'Edit tool, the original case' }
    @{ Want = $true;  Tool = 'Write'; Field = 'file_path'; V = 'D:/MyGame/.claude/.uea-install.json'; Why = 'Write to the install record' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "sed -i 's/COND_OwnerOnly/COND_None/' $A"; Why = 'sed -i, the bypass that was found' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "sed -E -i 's/a/b/' $A"; Why = 'sed with a flag before -i' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "echo hacked > $A"; Why = 'redirection over the file' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "echo more >> $A"; Why = 'appending redirection' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "cat <<'EOF' > $A`nstuff`nEOF"; Why = 'heredoc into the file' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "echo x | tee $A"; Why = 'tee onto the file' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "Set-Content -Path $A -Value 'x'"; Why = 'PowerShell Set-Content' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "rm $A"; Why = 'deleting an artefact' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "cp /tmp/forged.md $A"; Why = 'copying over the artefact' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "perl -pi -e 's/a/b/' $A"; Why = 'perl in place' }
    @{ Want = $true;  Tool = 'Bash'; Field = 'command'; V = "python -c 'x' && sed -i 's/a/b/' $A"; Why = 'second command in a chain' }

    # --- must pass ------------------------------------------------------------------------------
    @{ Want = $false; Tool = 'Edit'; Field = 'file_path'; V = 'C:/g/MyGame/Source/Thing.cpp'; Why = 'an ordinary source edit' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "cat $A"; Why = 'reading an artefact' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "grep -n COND $A"; Why = 'grepping an artefact' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "grep -rn COND MyGame/Docs/AgentMemory/ > /tmp/hits.txt"; Why = 'grep over artefacts, redirected elsewhere' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "cp $A /tmp/copy.md"; Why = 'copying an artefact out' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "ls -la MyGame/Docs/AgentMemory/classes"; Why = 'listing the directory' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "wc -l $A"; Why = 'counting lines' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "echo 'see MyGame/Docs/AgentMemory for artefacts' > notes.md"; Why = 'the path mentioned in text written elsewhere' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "sed -i 's/a/b/' MyGame/Source/Thing.cpp"; Why = 'sed -i on a source file' }
    @{ Want = $false; Tool = 'Bash'; Field = 'command'; V = "git status"; Why = 'an unrelated command' }
    @{ Want = $false; Tool = 'Read'; Field = 'file_path'; V = "C:/g/$A"; Why = 'reading via the Read tool' }
)

$bad = 0
foreach ($c in $cases) {
    $got = Ask $c.Tool $c.Field $c.V
    $ok = ($got -eq $c.Want)
    if (-not $ok) { $bad++ }
    $label = if ($c.Want) { 'deny ' } else { 'allow' }
    $mark = if ($ok) { '  ok  ' } else { ' WRONG' }
    Write-Host ("{0} expect {1}  {2}" -f $mark, $label, $c.Why) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
}
Write-Host ""
Write-Host "$($cases.Count - $bad) of $($cases.Count) correct."

$t = Measure-Command { 1..10 | ForEach-Object { (@{ tool_name='Bash'; tool_input=@{ command='git status' } } | ConvertTo-Json -Compress) | powershell -NoProfile -ExecutionPolicy Bypass -File $hook | Out-Null } }
Write-Host "cost on a Bash call with nothing to say: $([math]::Round($t.TotalMilliseconds/10)) ms"
