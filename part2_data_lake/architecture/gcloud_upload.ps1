# Upload project samples and metadata to Google Cloud Storage (PowerShell).
# Uploads only small sample and metadata files by default.
# It does not upload full raw datasets.
#
# Requirements:
#   - Google Cloud CLI (gcloud) installed and logged in: gcloud auth login
#   - A Google Cloud project with billing enabled.
#   - The environment variables below set. Do not hard-code secrets.
#
# Usage:
#   $env:GCP_PROJECT="your-project-id"
#   $env:GCS_BUCKET="part2-datalake-yourname"
#   ./gcloud_upload.ps1

$ErrorActionPreference = "Stop"

if (-not $env:GCP_PROJECT) { throw "Set GCP_PROJECT" }
if (-not $env:GCS_BUCKET)  { throw "Set GCS_BUCKET" }
$Location = if ($env:GCS_LOCATION) { $env:GCS_LOCATION } else { "us-east1" }

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$EvidenceDir = Join-Path $Root "architecture/cloud_evidence"
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$CmdLog = Join-Path $EvidenceDir "gcloud_commands_used.txt"
Set-Content -Path $CmdLog -Value ""

function Log-Cmd($Text) {
  # Record the command with the project and bucket names masked.
  $masked = $Text -replace $env:GCP_PROJECT, "<GCP_PROJECT>" -replace $env:GCS_BUCKET, "<GCS_BUCKET>"
  Add-Content -Path $CmdLog -Value $masked
}

Write-Host "Creating bucket if it does not exist..."
Log-Cmd "gcloud storage buckets create gs://$($env:GCS_BUCKET) --project $($env:GCP_PROJECT) --location $Location --uniform-bucket-level-access"
$exists = $true
try { gcloud storage buckets describe "gs://$($env:GCS_BUCKET)" --project $env:GCP_PROJECT 2>$null | Out-Null }
catch { $exists = $false }
if (-not $exists) {
  gcloud storage buckets create "gs://$($env:GCS_BUCKET)" `
    --project $env:GCP_PROJECT `
    --location $Location `
    --uniform-bucket-level-access | Out-Null
}

function Upload-Dir($LocalDir) {
  $src = Join-Path $Root $LocalDir
  if (Test-Path $src) {
    Write-Host "Uploading $LocalDir -> gs://$($env:GCS_BUCKET)/$LocalDir/"
    Log-Cmd "gcloud storage cp -r $src gs://$($env:GCS_BUCKET)/"
    gcloud storage cp -r $src "gs://$($env:GCS_BUCKET)/" --project $env:GCP_PROJECT | Out-Null
  }
}

Upload-Dir "metadata"
Upload-Dir "curated"
Upload-Dir "sample_data"

# Save cloud evidence: object list as manifest and a validation summary.
Write-Host "Saving cloud evidence to architecture/cloud_evidence/ ..."
Log-Cmd "gcloud storage ls -l -r gs://$($env:GCS_BUCKET)/**"
$lines = gcloud storage ls -l -r "gs://$($env:GCS_BUCKET)/**" --project $env:GCP_PROJECT 2>$null

$manifest = @("ObjectName,SizeBytes,Created")
foreach ($line in $lines) {
  $parts = ($line.Trim() -split "\s+")
  if ($parts.Length -ge 3 -and $parts[2].StartsWith("gs://")) {
    $name = $parts[2] -replace "gs://$($env:GCS_BUCKET)/", ""
    $manifest += "$name,$($parts[0]),$($parts[1])"
  }
}
Set-Content -Path (Join-Path $EvidenceDir "upload_manifest.csv") -Value $manifest

$count = $manifest.Count - 1
@(
  "Cloud validation",
  "Date: $(Get-Date)",
  "Bucket: <GCS_BUCKET> (name masked)",
  "Location: $Location",
  "Objects in bucket: $count",
  "Result: upload completed"
) | Set-Content -Path (Join-Path $EvidenceDir "cloud_validation.txt")

Write-Host "Upload complete. $count objects in gs://$($env:GCS_BUCKET)."
Write-Host "Evidence saved in architecture/cloud_evidence/."
