#!/bin/bash

############################################################################
#
#    @context — connect your MCP clients to the deployed instance, end to end.
#
#    Runs the three steps so you don't have to:
#      1. mint_mcp_jwt.py --write  — self-issue the keypair + admin token and
#                                    write CONTEXT_SELF_VERIFICATION_KEY (public
#                                    key) + CONTEXT_MCP_JWT (token) to
#                                    .env.production
#      2. railway/env-sync.sh      — push the public key so the deploy trusts
#                                    your token (the token itself stays local)
#      3. connect.py --production   — thread the token into Claude Code, Codex,
#                                    and Claude Desktop
#
#    Run from the repo root, inside the venv (source .venv/bin/activate).
#    Re-run any time to rotate the token. Pass --rotate-key to also regenerate
#    the signing keypair (invalidates previously minted tokens).
#
#    Usage:
#      ./scripts/setup_production_mcp.sh [--rotate-key] [--ttl-days N]
#
############################################################################

set -e

BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
cd "${REPO_ROOT}"

# Pick the venv python if we're not already in one (mint needs pyjwt + cryptography).
PY="python"
if [[ -z "$VIRTUAL_ENV" && -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PY="${REPO_ROOT}/.venv/bin/python"
fi

echo ""
echo -e "${BOLD}[1/3] Minting the self-issued MCP token${NC}"
"$PY" scripts/mint_mcp_jwt.py --write "$@"

echo ""
echo -e "${BOLD}[2/3] Syncing the public key to Railway${NC}"
./scripts/railway/env-sync.sh

echo ""
echo -e "${BOLD}[3/3] Wiring the token into your MCP clients${NC}"
"$PY" scripts/connect.py --production

echo ""
echo -e "${BOLD}Done.${NC}"
echo -e "${DIM}The token works once Railway finishes redeploying with the new public key."
echo -e "Restart Claude Desktop if it was configured; CLI clients pick it up immediately.${NC}"
echo ""
