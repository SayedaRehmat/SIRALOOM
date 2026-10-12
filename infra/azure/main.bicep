@description('Azure region for the SIRALOOM validation VM.')
param location string = resourceGroup().location
@description('Linux VM administrator username. Password authentication is disabled.')
param adminUsername string = 'siraloomadmin'
@description('SSH public key only. Never provide a private key.')
param sshPublicKey string
@description('CIDR allowed to SSH, e.g. 203.0.113.10/32. Never use 0.0.0.0/0.')
param adminCidr string
@description('VM size; benchmark capacity must be measured.')
param vmSize string = 'Standard_D2s_v5'
@minValue(128)
@maxValue(2048)
@description('Persistent managed data disk size in GiB.')
param dataDiskSizeGB int = 256
@description('Optional globally unique DNS label for the public IP.')
param dnsLabel string = ''

var vmName = 'siraloom-azure-validation'
var cloudInit = replace(loadTextContent('./cloud-init.yaml'), '__ADMIN_USERNAME__', adminUsername)

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'siraloom-validation-nsg'
  location: location
  properties: {
    securityRules: [
      {
        name: 'Allow-SSH-From-Admin-CIDR'
        properties: {
          priority: 100
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: adminCidr
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
      {
        name: 'Allow-HTTP'
        properties: {
          priority: 110
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '80'
        }
      }
      {
        name: 'Allow-HTTPS'
        properties: {
          priority: 120
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'siraloom-validation-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.42.0.0/16'] }
    subnets: [
      {
        name: 'siraloom-subnet'
        properties: {
          addressPrefix: '10.42.1.0/24'
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: 'siraloom-validation-pip'
  location: location
  sku: { name: 'Standard' }
  properties: union({
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }, empty(dnsLabel) ? {} : {
    dnsSettings: { domainNameLabel: dnsLabel }
  })
}

resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: 'siraloom-validation-nic'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'primary'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: { id: publicIp.id }
          subnet: { id: vnet.properties.subnets[0].id }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2023-09-01' = {
  name: vmName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    hardwareProfile: { vmSize: vmSize }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
      customData: base64(cloudInit)
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        name: '${vmName}-os'
        createOption: 'FromImage'
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
        diskSizeGB: 64
      }
      dataDisks: [
        {
          lun: 0
          name: 'siraloom-validation-data'
          createOption: 'Empty'
          diskSizeGB: dataDiskSizeGB
          managedDisk: { storageAccountType: 'StandardSSD_LRS' }
        }
      ]
    }
    networkProfile: {
      networkInterfaces: [
        { id: nic.id, properties: { primary: true } }
      ]
    }
  }
}

output vmName string = vm.name
output publicIpAddress string = publicIp.properties.ipAddress
output publicFqdn string = empty(dnsLabel) ? '' : publicIp.properties.dnsSettings.fqdn
output dataDiskSizeGB int = dataDiskSizeGB
output sshCommand string = 'ssh ${adminUsername}@${publicIp.properties.ipAddress}'
