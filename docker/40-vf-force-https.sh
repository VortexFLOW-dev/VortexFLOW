#!/bin/sh
# Enable http->https redirect for human traffic when VORTEXFLOW_FORCE_HTTPS is set.
# Agent bootstrap/metrics paths are exempted via the $vf_force_redirect map so a
# first-contact host (no cert trust yet) can still install and push metrics.
set -e
case "$(printf '%s' "${VORTEXFLOW_FORCE_HTTPS:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    cat > /etc/nginx/vortexflow-force-https.conf <<'CONF'
if ($vf_force_redirect) { return 301 https://$host$request_uri; }
CONF
    echo "vortexflow: forcing http->https for human traffic (agent paths exempt)"
    ;;
esac
