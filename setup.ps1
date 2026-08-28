# Crux - one-shot verification pass for Windows.
# Rebuilds the generated files, runs the parser tests, runs all five dry-run
# scenarios, and scores the gate. No API key, no internet. Nothing here costs
# money. Exit code is non-zero if anything is off.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$fail = 0

function Step($name, $block) {
    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host $name
    Write-Host ("=" * 70)
    try { & $block } catch { Write-Host "  FAILED: $_"; $script:fail = 1 }
}

Step "regenerate fixtures" { python orchestrator/fixtures/_build_fixtures.py }
Step "regenerate golden set" { python evals/build_golden_set.py }
Step "jsonio parser tests" {
    Push-Location orchestrator; python test_jsonio.py; if ($LASTEXITCODE) { $script:fail = 1 }; Pop-Location
}

$scenarios = @{
    "clean_disagreement" = "REPORT"    # real split, verdict withheld
    "resolved_crux"      = "REPORT"    # crux resolved in-pack, verdict issued
    "asymmetric"         = "REJECTED"  # symmetry + word budget fire pre-mediator
    "phantom_opponent"   = "REJECTED"  # phantom-opponent check fires
    "false_consensus"    = "REPORT"    # both sides agree, reported as consensus
}
foreach ($s in $scenarios.Keys) {
    Step "dry-run: $s  (expect $($scenarios[$s]))" {
        $out = python orchestrator/run.py --dry-run --scenario $s --seed 1 2>&1 | Out-String
        Write-Host $out
        if ($out -notmatch "TERMINAL STATE: $($scenarios[$s])") {
            Write-Host "  MISMATCH: expected $($scenarios[$s])"; $script:fail = 1
        }
    }
}

Step "gate evaluation (offline)" {
    $out = python evals/run_eval.py 2>&1 | Out-String
    Write-Host $out
    if ($out -notmatch "false block rate\s+0/") { Write-Host "  false blocks present"; $script:fail = 1 }
}

Write-Host ""
if ($fail) { Write-Host "SOMETHING IS BROKEN - see above."; exit 1 }
Write-Host "All checks passed."
