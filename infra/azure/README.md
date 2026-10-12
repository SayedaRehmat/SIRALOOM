# SIRALOOM Azure validation environment

This is the first Azure target for controlled software validation, not a high-availability or clinically qualified deployment. It runs the existing production Docker Compose topology on one Ubuntu VM: API, PostgreSQL, Redis, Celery worker, Celery Beat, and frontend. A persistent Azure managed disk is intended to hold database data, queue data, artifacts, references, cache, and scratch.

A single VM is a cost-conscious starting point but is a single point of failure. Do not use it for identifiable patient data or clinical reporting. Before lab use, complete security review, backup/restore, capacity, disaster-recovery, and laboratory qualification.

## Prerequisites

- Azure CLI logged into the intended subscription.
- An Azure resource group and a region where the chosen VM size is available.
- SSH key pair; supply only the public key to Bicep.
- The administrator's public IP/CIDR. SSH must not be open to the world.
- A DNS name you control before enabling public browser access.

## 1. Verify subscription

~~~bash
az login
az account list --output table
az account set --subscription "<YOUR_SUBSCRIPTION_ID>"
az account show --output table
az group create --name rg-siraloom-validation --location "<AZURE_REGION>"
~~~

Check student-credit expiry and budget in Azure Cost Management before provisioning. Never paste subscription credentials, private SSH keys, Firebase service-account JSON, database passwords, or provider keys into chat or GitHub.

## Windows PowerShell quick start

Since most deployment commands will be run from Windows PowerShell, this is the equivalent first pass. Run locally; do not send the SSH key or subscription details in chat.

~~~powershell
az login
az account list --output table
$subscriptionId = Read-Host "Paste the Azure subscription ID to use"
az account set --subscription $subscriptionId
az account show --output table

# Choose a region after checking availability and current credit/cost.
az account list-locations --output table
$location = Read-Host "Azure region name, e.g. eastus"
az group create --name rg-siraloom-validation --location $location

# Create an SSH key if you do not already have one.
if (-not (Test-Path "$HOME/.ssh/id_ed25519.pub")) {
  ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519"
}
$sshPublicKey = (Get-Content "$HOME/.ssh/id_ed25519.pub" -Raw).Trim()
$adminCidr = (Invoke-RestMethod -Uri "https://api.ipify.org").Trim() + "/32"

az bicep build --file infra/azure/main.bicep
az deployment group what-if --resource-group rg-siraloom-validation --template-file infra/azure/main.bicep --parameters location=$location adminCidr=$adminCidr sshPublicKey="$sshPublicKey" vmSize="Standard_D2s_v5" dataDiskSizeGB=256
~~~

Review the preview and ensure the SSH CIDR is your current public IP with /32. If your network changes, update the NSG rule before attempting SSH. Only after reviewing the what-if output, run the same command with what-if replaced by create:

~~~powershell
az deployment group create --resource-group rg-siraloom-validation --template-file infra/azure/main.bicep --parameters location=$location adminCidr=$adminCidr sshPublicKey="$sshPublicKey" vmSize="Standard_D2s_v5" dataDiskSizeGB=256
~~~

The deployment may take several minutes, and cloud-init continues after the VM resource is created. Verify the instance view and cloud-init completion before cloning the repository or copying data.

## 2. Preview and create infrastructure

From the repository root, Linux/macOS shell:

~~~bash
az bicep build --file infra/azure/main.bicep
az deployment group what-if --resource-group rg-siraloom-validation --template-file infra/azure/main.bicep --parameters adminCidr="<YOUR_PUBLIC_IP>/32" sshPublicKey="$(cat ~/.ssh/id_ed25519.pub)" vmSize="Standard_D2s_v5" dataDiskSizeGB=256
~~~

On Windows PowerShell, pass the contents of your .pub file as the sshPublicKey parameter. A small VM is for smoke tests only; benchmark capacity must be measured. Disk sizing must include reference packages, incoming VCFs, intermediates, reports, database growth, scratch peak, and backup headroom.

Review the what-if output before creating resources:

~~~bash
az deployment group create --resource-group rg-siraloom-validation --template-file infra/azure/main.bicep --parameters adminCidr="<YOUR_PUBLIC_IP>/32" sshPublicKey="$(cat ~/.ssh/id_ed25519.pub)" vmSize="Standard_D2s_v5" dataDiskSizeGB=256
~~~

The template creates a Linux VM, static public IP, VNet, NSG, SSH-key-only access, and persistent data disk. It opens inbound 22 only from the supplied CIDR, and ports 80/443 for a later TLS reverse proxy. API port 8000 and frontend port 3000 are not exposed publicly. The data disk is formatted/mounted at /data/siraloom on first boot.

Verify initialization:

~~~bash
az vm get-instance-view --resource-group rg-siraloom-validation --name siraloom-azure-validation --output table
ssh <ADMIN_USERNAME>@<PUBLIC_IP> 'cloud-init status --wait && lsblk && df -h /data/siraloom && docker compose version'
~~~

Do not delete/recreate the data disk as a troubleshooting shortcut. Confirm it is mounted and its UUID is in /etc/fstab before storing data.

## 3. Prepare the application on the VM

Clone and check out the exact commit that passed repository CI:

~~~bash
git clone https://github.com/SayedaRehmat/SIRALOOM.git
cd SIRALOOM
git checkout <QUALIFIED_COMMIT_SHA>
~~~

Create .env on the VM from .env.production.example, not in Git. Configure the production database/Redis URLs; persistent host paths under /data/siraloom; PUBLIC_BASE_URL, FRONTEND_ORIGIN and NEXT_PUBLIC_SIRALOOM_API_BASE; Firebase web settings and a valid Firebase Admin service-account JSON stored outside the repository; and reference paths only after the reference packages have been checksum-verified and registered.

Use chmod 600 for .env and Firebase credentials. Keep provider credentials server-side and enable a provider only after confirming its terms, limits, and suitability for non-clinical validation. Never leave example placeholders enabled. Confirm both GRCh37 and GRCh38 package identities, FASTA/FAI/contig manifests and checksums before testing normalization.

The existing Compose file binds API and frontend ports to VM loopback. Keep those bindings: do not expose 8000/3000 to the Internet. Configure Caddy on the VM host as the TLS reverse proxy. After DNS for your chosen hostname points to the VM public IP, install Caddy using its official Ubuntu repository instructions at https://caddyserver.com/docs/install, then:

~~~bash
sudo cp infra/azure/Caddyfile.example /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile  # replace YOUR_DNS_NAME with your actual DNS hostname
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
~~~

Run the copy command from the repository root; if Caddy is installed before cloning the repository, create the file from the example content manually. Replace the placeholder with a hostname you control that resolves to the VM. Caddy must be able to reach the public ACME service, and inbound 80/443 must be reachable for certificate issuance/renewal. Test HTTPS and certificate renewal behavior before using a browser. Set PUBLIC_BASE_URL and FRONTEND_ORIGIN to the final origin and set NEXT_PUBLIC_SIRALOOM_API_BASE to https://<YOUR_REAL_DNS_NAME>/api/v1 before building the frontend. Opening ports 80/443 alone is not TLS.

Until the reverse proxy and application are configured, use an SSH tunnel for controlled API smoke tests:

~~~bash
ssh -L 8000:127.0.0.1:8000 <ADMIN_USERNAME>@<PUBLIC_IP>
~~~

Then test http://127.0.0.1:8000/api/v1/health and /api/v1/ready locally. This is not a public deployment.

## 4. Start and verify

After reviewing environment values, secrets, storage mounts, and references:

~~~bash
docker compose --env-file .env -f docker-compose.production.yml config --quiet
docker compose --env-file .env -f docker-compose.production.yml build
docker compose --env-file .env -f docker-compose.production.yml up -d
docker compose --env-file .env -f docker-compose.production.yml ps
docker compose --env-file .env -f docker-compose.production.yml logs --tail=200 api worker
~~~

The API startup script applies Alembic migrations; the worker consumes tasks; exactly one Beat scheduler runs. Verify health/readiness, migration state, queue execution, persistent writes after a controlled restart, and backup/restore before benchmark submissions.

## 5. Gates before benchmark VCFs

1. Verify subscription/resource group, SSH restriction, disk mount, firewall, OS updates, Docker versions, TLS plan, and secret permissions.
2. Verify /api/v1/health and /api/v1/ready and database migration state.
3. Test Firebase authentication and tenant isolation with dedicated non-patient accounts.
4. Register and validate GRCh37/GRCh38 reference packages: exact build, FASTA/FAI/contig manifest, SHA-256, active state, and permissions.
5. Run the repository tests and deployment smoke tests against the deployed revision.
6. Use public benchmark VCFs only after checking license, provider terms, expected-truth set and reference compatibility. Record benchmark/version, expected variants, resource/tool versions, analysis IDs, logs, failures, and concordance. An HTTP 200 alone is not benchmark validation.
7. Exercise retries/restarts, worker loss, low disk, invalid reference, REF mismatch, provider timeouts/rate limits, and backup/restore.
8. Record evidence in the release acceptance matrix. Clinical use requires independent validation by the laboratory under its quality system.

## Cost control and limitations

- This is one VM, not HA; VM/disk failure interrupts service.
- PostgreSQL and Redis are containerized, not managed services, in this first validation stack.
- Artifact and reference files live on the attached disk; this is not an object-storage adapter. Plan off-VM backups.
- The template does not create DNS records, configure TLS, provision Firebase, transfer reference data, set provider credentials, or claim benchmark success.
- This does not qualify the separate lab-owned installer. That still requires reproducible installation, upgrade/rollback, local storage ownership, backups, and qualification on the lab's own infrastructure.
- Stop/deallocate the VM when not testing. Disks and public IP resources may continue to incur charges. Delete resources only after validation evidence and data have been intentionally preserved or discarded.
