# Local synthetic test only. Docker, Python and Scheduled Task commands are mocked.
param([Parameter(Mandatory)][string]$TestDirectory)
$ErrorActionPreference = 'Stop'
$base = (Resolve-Path -LiteralPath $TestDirectory).Path
$config = Join-Path $base 'operator.json'
$operator = Join-Path $base 'operator.py'
$oldImage = 'sha256:' + ('0' * 64)
$newImage = 'sha256:' + ('9' * 64)
$snapshotHash = '1' * 64
$script:canonicalSnapshotHash = $snapshotHash
$inventoryHash = '2' * 64
$snapshotPath = Join-Path $base 'final-public-snapshot.json'
Set-Content -LiteralPath $snapshotPath -Value '{}'
$common = @{ ConfigPath=$config; OperatorScript=$operator; ImageId=$newImage; SnapshotPath=$snapshotPath; SnapshotHash=$snapshotHash; LegacyInventoryHash=$inventoryHash }
$genesis = 'dd59a7a33d4d2796e52f985ff913b1f158fe09fa2d044fc63b17d24d2c0d0707'
$treasury = 'luxar1kyfg7ex2llzrctstgpkh7je50deyyvt9tfayug'
$null = Set-Content -LiteralPath $operator -Value '# synthetic'
@{ signer_image=$oldImage; genesis_hash=$genesis; tunnel_token_file='synthetic-not-a-credential' } | ConvertTo-Json | Set-Content -LiteralPath $config
$script:running = @{ 'luxartium-beta-signer'=$true; 'luxartium-beta-tunnel'=$true }
$script:enabled = $true
$script:logs = [Collections.Generic.List[string]]::new()
$wallets = @{}
for ($i=0; $i -lt 108; $i++) { $wallets["account-$i"] = "address-$i" }
$script:snapshot = @{ wallets=$wallets; operations=@{'operation-1'='hash-1'}; genesis=$genesis; treasury=$treasury }
function Get-ScheduledTask { param($TaskName); @{Settings=@{Enabled=$script:enabled}} }
function Disable-ScheduledTask { param($TaskName); $script:enabled=$false; $script:logs.Add('disable') }
function Enable-ScheduledTask { param($TaskName); $script:enabled=$true; $script:logs.Add('enable') }
function py {
  $script:running['luxartium-beta-signer']=$true; $script:running['luxartium-beta-tunnel']=$true
  $script:logs.Add('reconcile'); $global:LASTEXITCODE=0
  if ($script:injectMismatch) { $script:snapshot.operations['operation-1']='unexpected-hash' }
}
function docker {
  $global:LASTEXITCODE=0
  $a = @($args)
  if ($a[-1] -match "b64decode\('([^']+)'\)") { $a[-1] = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Matches[1])) }
  $script:logs.Add(($a[0..([Math]::Min(2,$a.Length-1))] -join ' '))
  if ($a[0] -eq 'container') {
    $name=$a[2]
    if ($name -eq 'luxartium-local-1') {
      return ConvertTo-Json -Depth 5 -InputObject @(@{Id='same-node'; Image='sha256:bcf43413a0ea468c0fd6c48826e64cabe41366987d0a7e7fdbf406f6693ea272'; Config=@{Labels=@{'io.aiartfoundry.luxartium'='localnet-v1'}}; State=@{Running=$true; StartedAt='same-time'}})
    }
    return ConvertTo-Json -Depth 5 -InputObject @(@{Id=$(if ($script:changeGeneration -and !$script:running['luxartium-beta-tunnel']) {'replaced-signer'} else {$name}); Config=@{Labels=@{'org.luxartium.private-beta'='signer-v1'}}; State=@{Running=$script:running[$name]}; Mounts=@(@{Destination='/state';Type='volume';Name=$(if ($script:wrongMount) {'different-volume'} else {'luxartium-beta-signer-state'});RW=$true})})
  }
  if ($a[0] -eq 'volume') { return ConvertTo-Json -Depth 5 -InputObject @(@{Labels=@{'org.luxartium.private-beta'='signer-v1'}}) }
  if ($a[0] -eq 'image') { return ConvertTo-Json -InputObject @(@{Id=$a[2]}) }
  if ($a[0] -eq 'stop') {
    $script:running[$a[-1]]=$false
    if ($a[-1] -eq 'luxartium-beta-tunnel') { $script:snapshot.operations['late-operation']='late-hash' }
    if ($a[-1] -eq 'luxartium-beta-signer') { $script:snapshot.operations['last-handler']='last-hash' }
    return $a[-1]
  }
  if ($a[0] -eq 'run' -and $a -contains 'sha256sum') { return '9e6525c54904c72f688b4c3d827ddda8fb7b1b0bdc938bd0ac395c1d5dcb6512  /usr/local/bin/luxartiumd' }
  if ($a[0] -eq 'run' -and $a[-1] -match 'welcome_policy.snapshot') {
    $script:logs.Add('validate-snapshot')
    return @{snapshot_hash=$script:canonicalSnapshotHash; legacy_inventory_hash=$inventoryHash; legacy_profiles=108} | ConvertTo-Json
  }
  if ($a[0] -eq 'run' -and $a -contains '/app/activate_welcome_policy.py') {
    $applied = $a -contains '--apply'
    $script:logs.Add($(if ($applied) {'activate-apply'} else {'activate-dry-run'}))
    if ($applied -and $script:injectActivationFailure) { throw 'Synthetic activation refused' }
    return @{applied=$applied; snapshot_hash=$script:canonicalSnapshotHash; legacy_inventory_hash=$inventoryHash} | ConvertTo-Json
  }
  if ($a[0] -eq 'run' -and $a[-1] -match 'sqlite3') { return $script:snapshot | ConvertTo-Json -Depth 5 }
  if ($a[0] -eq 'run' -and $a[-1] -match 'tarfile') {
    $mount = @($a | Where-Object { $_ -like 'type=bind,*' })[0]
    $destination = $mount.Substring('type=bind,source='.Length).Split(',')[0]
    $script:logs.Add('backup')
    Set-Content -LiteralPath (Join-Path $destination 'signer-state.tar') -Value 'synthetic archive, contains no keys'
    return ''
  }
  if ($a[0] -eq 'exec' -and $a[-1] -match 'sqlite3') {
    if ($script:pendingAfterIngressStop -and !$script:running['luxartium-beta-tunnel']) { throw 'Synthetic pending operation refused' }
    return $script:snapshot | ConvertTo-Json -Depth 5
  }
  if ($a[0] -eq 'exec' -and $a[-1] -match 'urllib') { return @{genesis_hash=$genesis; treasury_address=$treasury; welcome_policy=@{state='active'; policy_id='welcome-waterfall-v1'; snapshot_hash=$script:canonicalSnapshotHash; legacy_inventory_hash=$(if ($script:wrongHealthHash) {'3' * 64} else {$inventoryHash})}} | ConvertTo-Json -Depth 5 }
  throw 'Mock received an unexpected command; no external command was run.'
}
$recipe = [scriptblock]::Create((Get-Content -LiteralPath (Join-Path $PSScriptRoot 'docs\Upgrade-WelcomeSigner.ps1.example') -Raw))
$plan = & $recipe @common | ConvertFrom-Json
if ($plan.mode -ne 'plan' -or !$script:enabled -or !$script:running['luxartium-beta-signer']) { throw 'Read-only plan failed' }
$script:wrongMount=$true
$rejected=$false
try { $null=& $recipe @common -Execute } catch { $rejected=$_.Exception.Message -eq 'Running signer must use the exact current writable state volume.' }
if (!$rejected -or !$script:enabled -or $script:logs.Contains('disable') -or !$script:running['luxartium-beta-signer']) { throw 'Wrong state mount did not refuse before mutation' }
$script:wrongMount=$false
$logsBefore = $script:logs.Count
$wrong = $common.Clone(); $wrong.SnapshotHash='3' * 64
$rejected=$false
try { $null = & $recipe @wrong -Execute } catch { $rejected=$_.Exception.Message -eq 'Frozen welcome inventory hashes differ.' }
if (!$rejected -or !$script:enabled -or @($script:logs | Select-Object -Skip $logsBefore | Where-Object { $_ -eq 'disable' -or $_ -eq 'activate-apply' }).Count) { throw 'Wrong snapshot mutated state' }
$result = & $recipe @common -Execute | ConvertFrom-Json
if ($result.mode -ne 'complete' -or !$script:enabled -or $result.preserved_wallets -ne 108 -or $result.original_operations -ne 3) { throw 'Fresh offline upgrade baseline failed' }
if ((Get-Content -LiteralPath $config -Raw | ConvertFrom-Json).signer_image -ne $newImage) { throw 'Image update failed' }
if ($script:logs.IndexOf('disable') -gt $script:logs.IndexOf('stop --time 30')) { throw 'Recovery was not stopped first' }
if ($script:logs.IndexOf('backup') -gt $script:logs.IndexOf('activate-dry-run') -or $script:logs.IndexOf('activate-dry-run') -gt $script:logs.IndexOf('activate-apply') -or $script:logs.IndexOf('activate-apply') -gt $script:logs.IndexOf('reconcile')) { throw 'Activation was not ordered after backup and before restart' }
if ($script:logs.IndexOf('reconcile') -gt $script:logs.IndexOf('enable')) { throw 'Recovery enabled too early' }
if (!(Test-Path -LiteralPath (Join-Path $result.backup_directory 'signer-state.tar'))) { throw 'Backup absent' }
$savedBaseline = Get-Content -LiteralPath (Join-Path $result.backup_directory 'mapping.before.json') -Raw | ConvertFrom-Json
if ($savedBaseline.operations.'late-operation' -ne 'late-hash' -or $savedBaseline.operations.'last-handler' -ne 'last-hash') { throw 'Fresh baseline lost an admitted operation' }
$script:injectMismatch = $true
$rejected = $false
try { $null = & $recipe @common -Execute }
catch { $rejected = $_.Exception.Message -like 'Signer validation failed*' }
if (!$rejected -or $script:enabled -or $script:running['luxartium-beta-signer'] -or $script:running['luxartium-beta-tunnel']) { throw 'Mismatch did not fail closed' }
$script:injectMismatch=$false
$script:pendingAfterIngressStop=$true
$script:running['luxartium-beta-signer']=$true
$script:running['luxartium-beta-tunnel']=$true
$script:enabled=$true
$configBeforePending = Get-Content -LiteralPath $config -Raw
$backupCountBefore = @(Get-ChildItem -LiteralPath $base -Filter 'signer-state.tar' -Recurse).Count
$rejected = $false
try { $null = & $recipe @common -Execute }
catch { $rejected = $_.Exception.Message -eq 'Synthetic pending operation refused' }
if (!$rejected -or $script:enabled -or $script:running['luxartium-beta-tunnel']) { throw 'Pending operation not refused under disabled recovery/closed ingress' }
if ($configBeforePending -cne (Get-Content -LiteralPath $config -Raw) -or $backupCountBefore -ne @(Get-ChildItem -LiteralPath $base -Filter 'signer-state.tar' -Recurse).Count) { throw 'Pending operation changed configuration or created backup' }
$script:pendingAfterIngressStop=$false
$script:wrongHealthHash=$true
$script:running['luxartium-beta-signer']=$true
$script:running['luxartium-beta-tunnel']=$true
$script:enabled=$true
$rejected=$false
try { $null=& $recipe @common -Execute } catch { $rejected=$_.Exception.Message -like 'Signer validation failed*' }
if (!$rejected -or $script:enabled -or $script:running['luxartium-beta-signer'] -or $script:running['luxartium-beta-tunnel']) { throw 'Wrong active inventory did not fail closed' }
$script:wrongHealthHash=$false
$script:changeGeneration=$true
$script:running['luxartium-beta-signer']=$true
$script:running['luxartium-beta-tunnel']=$true
$script:enabled=$true
$rejected=$false
$previousBackupCount=@(Get-ChildItem -LiteralPath $base -Filter 'signer-state.tar' -Recurse).Count
try { $null=& $recipe @common -Execute } catch { $rejected=$_.Exception.Message -eq 'Signer generation changed before offline backup.' }
if (!$rejected -or $script:enabled -or $previousBackupCount -ne @(Get-ChildItem -LiteralPath $base -Filter 'signer-state.tar' -Recurse).Count) { throw 'Replaced signer was used as backup baseline' }
$script:changeGeneration=$false
$script:injectActivationFailure=$true
$script:running['luxartium-beta-signer']=$true
$script:running['luxartium-beta-tunnel']=$true
$script:enabled=$true
$configBeforeActivation=Get-Content -LiteralPath $config -Raw
$rejected=$false
try { $null=& $recipe @common -Execute } catch { $rejected=$_.Exception.Message -eq 'Synthetic activation refused' }
if (!$rejected -or $script:enabled -or $script:running['luxartium-beta-signer'] -or $script:running['luxartium-beta-tunnel'] -or $configBeforeActivation -cne (Get-Content -LiteralPath $config -Raw)) { throw 'Failed offline activation did not retain stopped writer and original config' }
Write-Output 'PASS synthetic plan, fresh offline baseline race, controlled upgrade, mapping-mismatch fail-closed, pending-operation refusal before backup/config change, snapshot/hash guards, backup-before-activation order and offline activation failure. All Docker/task/Python operations mocked; no live credentials/resources.'
