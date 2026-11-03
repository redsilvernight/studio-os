<#
.SYNOPSIS
  Copie hors site de la dernière sauvegarde du VPS (docker/backup.sh) vers un disque local.

.DESCRIPTION
  Rapatrie par scp le dernier répertoire <AAAAMMJJTHHMMSSZ> de -RemoteRoot s'il est absent
  localement, vérifie l'empreinte SHA-256 du dump, le nombre et la taille des fichiers,
  puis ne conserve que les -Keep copies les plus récentes. Pensé pour une tâche planifiée
  qui rattrape les créneaux manqués (poste éteint la nuit) : sans nouvelle sauvegarde,
  il ne fait rien.
#>
param(
    [string]$Destination = 'E:\StudioOS-backups',
    [ValidateRange(1, 30)][int]$Keep = 3,
    [string]$RemoteHost = 'ubuntu@57.131.136.131',
    [string]$RemoteRoot = '/home/ubuntu/studio-backups',
    [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh\binaweb_vps')
)
$ErrorActionPreference = 'Stop'
$pattern = '^\d{8}T\d{6}Z$'
New-Item -ItemType Directory -Force $Destination | Out-Null
$log = Join-Path $Destination 'pull.log'
function Write-Log([string]$Message) {
    $line = '{0:u} {1}' -f (Get-Date).ToUniversalTime(), $Message
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
    $line
}
$ssh = @('-i', $KeyPath, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20')

try {
    $latest = (& ssh @ssh $RemoteHost "ls -1 '$RemoteRoot' | grep -E '^[0-9]{8}T[0-9]{6}Z$' | sort | tail -n 1").Trim()
    if ($LASTEXITCODE -ne 0 -or $latest -notmatch $pattern) { throw "aucune sauvegarde distante lisible ($latest)" }
    $final = Join-Path $Destination $latest
    if (Test-Path -LiteralPath $final) {
        Write-Log "à jour : $latest déjà présent"
    } else {
        # Contrôle distant : sha256 du dump, nombre de fichiers, octets.
        $remote = & ssh @ssh $RemoteHost "cd '$RemoteRoot/$latest' && sha256sum postgres/studio.dump | cut -d' ' -f1 && find . -type f | wc -l && find . -type f -printf '%s\n' | awk '{s+=`$1} END {print s+0}'"
        if ($LASTEXITCODE -ne 0 -or $remote.Count -ne 3) { throw "contrôle distant impossible pour $latest" }
        $partial = Join-Path $Destination ".partial-$latest"
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Recurse -Force }
        New-Item -ItemType Directory $partial | Out-Null
        & scp @ssh -q -r "${RemoteHost}:$RemoteRoot/$latest/*" $partial
        if ($LASTEXITCODE -ne 0) { throw "scp a échoué ($LASTEXITCODE)" }
        $files = Get-ChildItem -LiteralPath $partial -Recurse -File
        $hash = (Get-FileHash -LiteralPath (Join-Path $partial 'postgres\studio.dump') -Algorithm SHA256).Hash.ToLower()
        $bytes = ($files | Measure-Object Length -Sum).Sum
        if ($hash -ne $remote[0].Trim() -or $files.Count -ne [int]$remote[1] -or $bytes -ne [long]$remote[2]) {
            throw "copie incohérente : sha=$hash/$($remote[0]) fichiers=$($files.Count)/$($remote[1]) octets=$bytes/$($remote[2])"
        }
        Rename-Item -LiteralPath $partial -NewName $latest
        Write-Log "copié : $latest ($($files.Count) fichiers, $bytes octets, dump $hash)"
    }
    # Rétention : seulement les répertoires complets au format horodaté.
    Get-ChildItem -LiteralPath $Destination -Directory |
        Where-Object Name -match $pattern | Sort-Object Name -Descending |
        Select-Object -Skip $Keep | ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
            Write-Log "supprimé (rétention $Keep) : $($_.Name)"
        }
} catch {
    Write-Log "ERREUR : $($_.Exception.Message)"
    exit 1
}
