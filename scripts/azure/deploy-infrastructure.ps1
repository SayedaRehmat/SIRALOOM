[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroup,
    [Parameter(Mandatory = $true)]
    [string]$Location,
    [Parameter(Mandatory = $true)]
    [string]$AdminCidr,
    [string]$SshPublicKeyPath = "$HOME/.ssh/id_ed25519.pub",
    [string]$VmSize = "Standard_D2s_v5",
    [ValidateRange(128, 2048)]
    [int]$DataDiskSizeGB = 256,
    [string]$DnsLabel = ""
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI (az) is required. Install it from https://learn.microsoft.com/cli/azure/install-azure-cli"
}
if (-not (Test-Path -LiteralPath $SshPublicKeyPath -PathType Leaf)) {
    throw "SSH public key not found at '$SshPublicKeyPath'. Pass the .pub path. Never pass a private key."
}
if ($AdminCidr -notmatch '^([0-9]{1,3}\.){3}[0-9]{1,3}/32$') {
    throw "AdminCidr must be one IPv4 address with /32, e.g. 203.0.113.10/32. Do not open SSH to a network range."
}
$ipText = $AdminCidr.Substring(0, $AdminCidr.LastIndexOf('/'))
$parsedIp = $null
if (-not [System.Net.IPAddress]::TryParse($ipText, [ref]$parsedIp) -or
    $parsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "AdminCidr does not contain a valid IPv4 address."
}

Write-Host "Checking Azure CLI session."
az account show --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    az login
    if ($LASTEXITCODE -ne 0) { throw "Azure login failed." }
}
az account set --subscription $SubscriptionId
if ($LASTEXITCODE -ne 0) { throw "Could not select the requested subscription." }
$activeSubscription = az account show --query id --output tsv
if ($LASTEXITCODE -ne 0 -or $activeSubscription -ne $SubscriptionId) {
    throw "Active Azure subscription does not match the requested subscription ID."
}

$sshPublicKey = (Get-Content -LiteralPath $SshPublicKeyPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($sshPublicKey) -or $sshPublicKey -notmatch '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-)') {
    throw "The supplied file does not look like an SSH public key."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$template = Join-Path $repoRoot "infra/azure/main.bicep"
if (-not (Test-Path -LiteralPath $template)) { throw "Bicep template not found: $template" }

Write-Host "Subscription: $activeSubscription"
Write-Host "Resource group: $ResourceGroup"
Write-Host "Region: $Location"
Write-Host "SSH allow-list: $AdminCidr"
Write-Host "VM size: $VmSize; data disk: $DataDiskSizeGB GiB"
Write-Host "Check Azure Cost Management and student-credit expiry before continuing."

az group create --name $ResourceGroup --location $Location --output none
if ($LASTEXITCODE -ne 0) { throw "Resource group creation failed." }

az bicep build --file $template
if ($LASTEXITCODE -ne 0) { throw "Bicep compilation failed." }

$parameters = @(
    "location=$Location",
    "adminCidr=$AdminCidr",
    "sshPublicKey=$sshPublicKey",
    "vmSize=$VmSize",
    "dataDiskSizeGB=$DataDiskSizeGB",
    "dnsLabel=$DnsLabel"
)

Write-Host ""
Write-Host "Previewing Azure changes. Review the entire result before deployment."
az deployment group what-if --resource-group $ResourceGroup --template-file $template --parameters $parameters
if ($LASTEXITCODE -ne 0) { throw "Azure what-if failed; no deployment was requested." }

$confirmation = Read-Host "Type DEPLOY to create the VM, public IP, network, and persistent data disk"
if ($confirmation -cne "DEPLOY") {
    Write-Host "Cancelled. No infrastructure deployment was requested."
    exit 0
}

$deploymentName = "siraloom-validation-$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))"
az deployment group create --name $deploymentName --resource-group $ResourceGroup --template-file $template --parameters $parameters --output json
if ($LASTEXITCODE -ne 0) { throw "Azure deployment failed. Inspect deployment operation errors before retrying." }

Write-Host ""
Write-Host "Infrastructure deployment request completed. Verify VM provisioning and cloud-init before copying data."
az vm get-instance-view --resource-group $ResourceGroup --name siraloom-azure-validation --output table
