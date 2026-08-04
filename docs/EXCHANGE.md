# Exchange configuration

MailGate sends accepted messages to Exchange by SMTP. Create a dedicated Receive Connector restricted to the Synology or Docker gateway source IP.

## Example assumptions

```text
Exchange server: 192.168.177.13
MailGate/Synology source IP: 192.168.177.220
SMTP port: 25
```

## Recommended connector properties

- Bind to the internal Exchange interface.
- Allow only the MailGate source IP.
- Permit anonymous SMTP for that source IP.
- Accept recipients only in Exchange authoritative domains.
- Do not grant unrestricted external relay permissions.

For Exchange Management Shell, adapt this example:

```powershell
New-ReceiveConnector `
  -Name "MailGate" `
  -Server "EXCHANGE01" `
  -TransportRole FrontendTransport `
  -Bindings 0.0.0.0:25 `
  -RemoteIPRanges 192.168.177.220 `
  -Usage Custom

Set-ReceiveConnector "EXCHANGE01\MailGate" `
  -PermissionGroups AnonymousUsers
```

Do not add `Ms-Exch-SMTP-Accept-Any-Recipient` unless MailGate must relay to domains that are not authoritative in the Exchange organization.

## Connectivity test

From the Synology host:

```bash
nc -vz 192.168.177.13 25
```

Then inspect the Postfix queue and logs after sending a test message.
