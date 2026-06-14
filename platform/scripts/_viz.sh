# Shared terminal visualization for the e2e / coverage scripts.
# Source it:  . "$(dirname "$0")/_viz.sh"
# Honours NO_COLOR and non-TTY (plain output). Counters: FAILS, WARNS.

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then _VIZ_TTY=1; else _VIZ_TTY=0; fi
_vc() { if [ "$_VIZ_TTY" = 1 ]; then printf '\033[%sm%s\033[0m' "$1" "$2"; else printf '%s' "$2"; fi; }
green()  { _vc 32 "$*"; }
red()    { _vc 31 "$*"; }
yellow() { _vc 33 "$*"; }
cyan()   { _vc 36 "$*"; }
dim()    { _vc 2  "$*"; }
bold()   { _vc 1  "$*"; }

hr()      { dim "──────────────────────────────────────────────────────────────────────"; echo; }
section() { echo; _vc '1;36' "▶ $*"; echo; }
group()   { printf '  %s\n' "$(bold "$*")"; }   # sub-heading inside a section

ok()   { printf '  %s %s\n' "$(green '✓')"  "$*"; }
warn() { printf '  %s %s\n' "$(yellow '⚠')" "$*"; WARNS=$(( ${WARNS:-0} + 1 )); }
fail() { printf '  %s %s\n' "$(red '✗')"    "$*"; FAILS=$(( ${FAILS:-0} + 1 )); }

# assertion helpers (same signatures the e2e scripts already use)
check() { if [ "$2" = "$3" ]; then ok "$1 ($2)"; else fail "$1 $(dim "— got '$2' expected '$3'")"; fi; }
has()   { if printf '%s' "$2" | grep -q -- "$3"; then ok "$1"; else fail "$1 $(dim "— missing '$3'")"; fi; }
hasnt() { if printf '%s' "$2" | grep -q -- "$3"; then fail "$1 $(dim "— unexpected '$3'")"; else ok "$1"; fi; }
num()   { if python3 -c "import sys;x=float('${2:-nan}');sys.exit(0 if ($3) else 1)" 2>/dev/null; then ok "$1 $(dim "($2)")"; else fail "$1 $(dim "— value=$2 fails $3")"; fi; }

# final banner from the FAILS counter
result() {
  echo
  if [ "${FAILS:-0}" -eq 0 ]; then
    printf '%s' "$(green "✅ $* PASSED")"
    [ "${WARNS:-0}" -gt 0 ] && printf '%s' "$(dim "  (${WARNS} warnings)")"
    echo
  else
    echo "$(red "❌ $* FAILED")  $(dim "(${FAILS} checks${WARNS:+, ${WARNS} warnings})")"
  fi
}
