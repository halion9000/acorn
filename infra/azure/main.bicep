// Live Oak operations in Azure: one private network, a Linux VM for A.C.O.R.N, a Windows VM for CORE, a managed Postgres, a Key Vault, backups and a budget.
//
// Nothing here is reachable from the internet: the VMs have no public address, the network rules refuse inbound traffic from the internet, and Postgres has no public endpoint. Reach the machines through
// the RMM tool or a private mesh network (see docs/AZURE_MIGRATION_PLAN.md). Outbound traffic is open because the system has to call vendor APIs.
//
// Deploy into an EXISTING resource group (create it first, with a budget), preview with `what-if`, then deploy. See infra/azure/README.md.

targetScope = 'resourceGroup'

@description('Azure region. The same region is used for everything so traffic between the pieces stays local.')
param location string = 'centralus'

@description('A short name used in resource names.')
@minLength(3)
@maxLength(12)
param prefix string = 'liveoak'

@description('Address space of the private network.')
param vnetAddressPrefix string = '10.20.0.0/16'

@description('Size of the A.C.O.R.N Linux VM (about 5 GB of memory is used today, so 16 GB leaves room to grow).')
param acornVmSize string = 'Standard_D4s_v6'

@description('Size of the CORE Windows VM. A burstable size is enough: CORE is mostly idle with short busy periods.')
param coreVmSize string = 'Standard_B2ms'

@description('Size of the managed Postgres server (Burstable tier).')
param postgresSku string = 'Standard_B2s'

@description('Storage for Postgres in GB (the database is about 1 GB today).')
param postgresStorageGb int = 64

@description('Postgres major version.')
param postgresVersion string = '16'

@description('Data disk for the A.C.O.R.N stores (ClickHouse, OpenSearch, Neo4j, Qdrant, Kafka, Redis) in GB.')
param acornDataDiskGb int = 128

@description('Administrator user name for both VMs and for Postgres.')
param adminUser string = 'liveoakadmin'

@description('The SSH public key for the Linux VM (the private key stays with you; there is no password login).')
param sshPublicKey string

@secure()
@description('Administrator password for the Windows VM. Generated at deploy time and stored in Key Vault; never put in a file.')
param coreAdminPassword string

@secure()
@description('Administrator password for Postgres. Generated at deploy time and stored in Key Vault; never put in a file.')
param postgresAdminPassword string

@description('Monthly budget for this resource group, in US dollars. Alerts go out at 50 and 80 percent.')
param monthlyBudget int = 450

@description('Who gets the budget alerts.')
param budgetEmail string

@description('Start date of the budget (first day of a month), for example 2026-11-01.')
param budgetStart string

var tags = {
  project: 'liveoak-ops'
  managedBy: 'bicep'
}

var names = {
  vnet: '${prefix}-vnet'
  nsgApp: '${prefix}-nsg-app'
  nsgCore: '${prefix}-nsg-core'
  nsgData: '${prefix}-nsg-data'
  acorn: '${prefix}-acorn-vm'
  core: '${prefix}-core-vm'
  postgres: '${prefix}-pg-${uniqueString(resourceGroup().id)}'
  keyVault: '${prefix}-kv-${uniqueString(resourceGroup().id)}'
  recovery: '${prefix}-rsv'
  logs: '${prefix}-logs'
}

// ---- network ---------------------------------------------------------------------------------------------------------------------------------------

// Refuses inbound traffic from the internet and allows traffic inside the network. Azure's own default rules already allow the network to talk to itself; the explicit deny makes the intent
// visible and survives a later public address being attached by mistake.
var lockedDownRules = [
  {
    name: 'deny-internet-inbound'
    properties: {
      priority: 4000
      direction: 'Inbound'
      access: 'Deny'
      protocol: '*'
      sourceAddressPrefix: 'Internet'
      sourcePortRange: '*'
      destinationAddressPrefix: '*'
      destinationPortRange: '*'
    }
  }
]

resource nsgApp 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: names.nsgApp
  location: location
  tags: tags
  properties: { securityRules: lockedDownRules }
}

resource nsgCore 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: names.nsgCore
  location: location
  tags: tags
  properties: { securityRules: lockedDownRules }
}

resource nsgData 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: names.nsgData
  location: location
  tags: tags
  properties: { securityRules: lockedDownRules }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: names.vnet
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [vnetAddressPrefix] }
    subnets: [
      {
        name: 'snet-app'
        properties: {
          addressPrefix: cidrSubnet(vnetAddressPrefix, 24, 1)
          networkSecurityGroup: { id: nsgApp.id }
        }
      }
      {
        name: 'snet-core'
        properties: {
          addressPrefix: cidrSubnet(vnetAddressPrefix, 24, 2)
          networkSecurityGroup: { id: nsgCore.id }
        }
      }
      {
        // Postgres lives here, reachable only from inside the network.
        name: 'snet-data'
        properties: {
          addressPrefix: cidrSubnet(vnetAddressPrefix, 24, 3)
          networkSecurityGroup: { id: nsgData.id }
          delegations: [
            {
              name: 'postgres'
              properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' }
            }
          ]
        }
      }
    ]
  }
}

resource snetApp 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = {
  parent: vnet
  name: 'snet-app'
}

resource snetCore 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = {
  parent: vnet
  name: 'snet-core'
}

resource snetData 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = {
  parent: vnet
  name: 'snet-data'
}

// ---- Postgres ---------------------------------------------------------------------------------------------------------------------------------------

resource pgDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: '${prefix}.private.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource pgDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: pgDns
  name: '${prefix}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: names.postgres
  location: location
  tags: tags
  sku: {
    name: postgresSku
    tier: 'Burstable'
  }
  properties: {
    version: postgresVersion
    administratorLogin: adminUser
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: postgresStorageGb }
    backup: {
      backupRetentionDays: 14
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: snetData.id
      privateDnsZoneArmResourceId: pgDns.id
      publicNetworkAccess: 'Disabled'
    }
  }
  dependsOn: [pgDnsLink]
}

resource pgDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'aisoc'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Extensions A.C.O.R.N uses in its migrations (trigram search, UUIDs) have to be allowed on a managed server before they can be created.
resource pgExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: {
    value: 'PG_TRGM,PGCRYPTO,UUID-OSSP,BTREE_GIN,CITEXT'
    source: 'user-override'
  }
  dependsOn: [pgDatabase]
}

// ---- secrets ----------------------------------------------------------------------------------------------------------------------------------------

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: names.keyVault
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
  }
}

resource coreAdminSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'core-vm-admin-password'
  properties: { value: coreAdminPassword }
}

resource pgAdminSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'postgres-admin-password'
  properties: { value: postgresAdminPassword }
}

// ---- virtual machines -------------------------------------------------------------------------------------------------------------------------------

resource acornNic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${names.acorn}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: { id: snetApp.id }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}

resource acornDataDisk 'Microsoft.Compute/disks@2023-10-02' = {
  name: '${names.acorn}-data'
  location: location
  tags: tags
  sku: { name: 'Premium_LRS' }
  properties: {
    creationData: { createOption: 'Empty' }
    diskSizeGB: acornDataDiskGb
  }
}

resource acornVm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: names.acorn
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    hardwareProfile: { vmSize: acornVmSize }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 64
        managedDisk: { storageAccountType: 'Premium_LRS' }
      }
      dataDisks: [
        {
          lun: 0
          createOption: 'Attach'
          managedDisk: { id: acornDataDisk.id }
        }
      ]
    }
    osProfile: {
      computerName: 'acorn'
      adminUsername: adminUser
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUser}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: { networkInterfaces: [{ id: acornNic.id }] }
  }
}

resource coreNic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${names.core}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: { id: snetCore.id }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}

resource coreVm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: names.core
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    hardwareProfile: { vmSize: coreVmSize }
    storageProfile: {
      imageReference: {
        publisher: 'MicrosoftWindowsServer'
        offer: 'WindowsServer'
        sku: '2022-datacenter-azure-edition'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 128
        managedDisk: { storageAccountType: 'Premium_LRS' }
      }
    }
    osProfile: {
      computerName: 'core'
      adminUsername: adminUser
      adminPassword: coreAdminPassword
      windowsConfiguration: {
        enableAutomaticUpdates: true
        patchSettings: {
          patchMode: 'AutomaticByPlatform'
          assessmentMode: 'AutomaticByPlatform'
        }
      }
    }
    networkProfile: { networkInterfaces: [{ id: coreNic.id }] }
  }
}

// Each VM may read its own secrets from Key Vault (role: Key Vault Secrets User).
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource acornReadsSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, acornVm.id, keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: acornVm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource coreReadsSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, coreVm.id, keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: coreVm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---- backups ----------------------------------------------------------------------------------------------------------------------------------------

resource recovery 'Microsoft.RecoveryServices/vaults@2024-04-01' = {
  name: names.recovery
  location: location
  tags: tags
  sku: {
    name: 'RS0'
    tier: 'Standard'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
  }
}

resource backupPolicy 'Microsoft.RecoveryServices/vaults/backupPolicies@2024-04-01' = {
  parent: recovery
  name: 'daily-14-days'
  properties: {
    backupManagementType: 'AzureIaasVM'
    policyType: 'V2'
    instantRPDetails: {}
    instantRpRetentionRangeInDays: 2
    schedulePolicy: {
      schedulePolicyType: 'SimpleSchedulePolicyV2'
      scheduleRunFrequency: 'Daily'
      dailySchedule: { scheduleRunTimes: ['2026-01-01T06:00:00Z'] }
    }
    retentionPolicy: {
      retentionPolicyType: 'LongTermRetentionPolicy'
      dailySchedule: {
        retentionTimes: ['2026-01-01T06:00:00Z']
        retentionDuration: {
          count: 14
          durationType: 'Days'
        }
      }
    }
    timeZone: 'UTC'
  }
}

resource acornBackup 'Microsoft.RecoveryServices/vaults/backupFabrics/protectionContainers/protectedItems@2024-04-01' = {
  name: '${recovery.name}/Azure/iaasvmcontainer;iaasvmcontainerv2;${resourceGroup().name};${acornVm.name}/vm;iaasvmcontainerv2;${resourceGroup().name};${acornVm.name}'
  properties: {
    protectedItemType: 'Microsoft.Compute/virtualMachines'
    policyId: backupPolicy.id
    sourceResourceId: acornVm.id
  }
}

resource coreBackup 'Microsoft.RecoveryServices/vaults/backupFabrics/protectionContainers/protectedItems@2024-04-01' = {
  name: '${recovery.name}/Azure/iaasvmcontainer;iaasvmcontainerv2;${resourceGroup().name};${coreVm.name}/vm;iaasvmcontainerv2;${resourceGroup().name};${coreVm.name}'
  properties: {
    protectedItemType: 'Microsoft.Compute/virtualMachines'
    policyId: backupPolicy.id
    sourceResourceId: coreVm.id
  }
}

// ---- logs and budget --------------------------------------------------------------------------------------------------------------------------------

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logs
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    // A cap so a noisy log cannot become a surprise bill.
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: '${prefix}-monthly'
  properties: {
    category: 'Cost'
    amount: monthlyBudget
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStart }
    notifications: {
      half: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: [budgetEmail]
      }
      most: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [budgetEmail]
      }
      forecast: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [budgetEmail]
      }
    }
  }
}

// ---- what to know after a deploy -------------------------------------------------------------------------------------------------------------------

output acornPrivateIp string = acornNic.properties.ipConfigurations[0].properties.privateIPAddress
output corePrivateIp string = coreNic.properties.ipConfigurations[0].properties.privateIPAddress
output postgresHost string = '${postgres.name}.${prefix}.private.postgres.database.azure.com'
output keyVaultName string = keyVault.name
