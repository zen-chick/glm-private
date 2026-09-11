# Security policy

## Private deployment

- Keep this repository private and require two-factor authentication on GitHub.
- Never commit `~/.glm`, API keys, authentication tokens, audit databases, signing keys, or production APKs.
- GitHub stores source and CI artifacts only. It is not the runtime connection path.
- Connect Android clients through a private Tailnet. Do not open port 8765 on the router and do not use Tailscale Funnel.
- Restrict the Tailnet ACL to the owner's account and enrolled Xperia device.
- Run GLM Core without administrator privileges.

## Android signing

The production signing key is generated under `~/.glm/signing` and its password is protected with Windows DPAPI. Back up the keystore and encrypted password file together to offline encrypted storage. Loss of the key prevents seamless application updates.

## Incident response

If a phone is lost, remove it from the Tailnet, rotate `~/.glm/auth_token`, and reinstall or re-pair GLM Remote. Review the GLM audit database before restoring access.