# TLS & Certificates

VortexFlow terminates TLS at its nginx front door and manages certificates from a
built-in **cert store** under **Settings → Certificates**.

## Default: self-signed CA

Out of the box, VortexFlow generates a **self-signed CA** and certificate so the
stack works over HTTPS immediately — including [agents](../reference/agent.md),
which are configured to trust that CA so the config-pull channel is authenticated
and encrypted. Browsers will warn on the self-signed cert; that's expected for
local and test use.

For any real deployment, install a proper certificate.

## The cert store

The Certificates tab lets you manage TLS material:

- **Upload** a PEM certificate and private key, with an optional CA chain and
  notes.
- Private keys are **encrypted at rest** (Fernet) — they aren't stored in
  plaintext.
- Each certificate shows parsed details: common name, SANs, extended key usage,
  and an **expiry badge** that shifts green → amber → red → expired as the date
  approaches, so you see renewals coming.
- Certificate type (server / CA / client) is detected and shown for clarity.

## Applying a certificate

Applying a server certificate writes the PEM files to VortexFlow's certificate
directory atomically and puts them into service behind nginx. Replacing an
expiring cert is an upload-then-apply, without hand-editing files on disk.

## Expiry awareness

Because expiry is the most common cause of an outage, VortexFlow surfaces it
prominently: the expiry badges in the cert store, and (optionally) a
[notification](notifications.md) as a certificate nears its expiry date.

## Recommendations

- Use a certificate from your own CA or a public CA for anything beyond local
  testing.
- Keep the CA chain attached so clients and agents validate the full path.
- Watch the expiry badges and wire up a notification channel so a renewal never
  surprises you.
