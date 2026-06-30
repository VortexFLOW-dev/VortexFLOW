# White-labeling

VortexFlow can present under your own application name. This is handy for managed
service providers and internal platform teams who want the tool to carry a
house brand.

## Application name

Under **Settings → General**, set the **Application name**. It replaces
"VortexFlow" in:

- the **sidebar** brand,
- the **browser tab** title, and
- the **login page**.

The name is capped at **40 characters** so a long brand can't break the sidebar
or login layout — the field enforces the limit as you type, and the server
rejects anything longer. A long-but-valid name is truncated with an ellipsis in
the fixed-width sidebar (with the full name available on hover).

## Scope

White-labeling currently covers the application name. It does **not** change the
underlying product, the generated Vector config (which is always standard Vector
YAML regardless of branding), or licensing.

## Notes

- The change applies globally for all users of that VortexFlow instance.
- Logo replacement and fuller theming are not part of the current
  white-labeling surface.
