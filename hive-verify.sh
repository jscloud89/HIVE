#!/bin/bash
# ============================================================
# HIVE Agent Verification Test Harness
# Beelink SER5 Max · beekeeper@192.168.50.10
# Run as: bash hive-verify.sh
# ============================================================

HIVE_ROOT="$HOME/HIVE"
HIVE_PHASE1="$HOME/hive-phase1"
DATA_DIR="$HIVE_PHASE1/data"
LOG_DIR="$DATA_DIR/logs"
PASS=0
FAIL=0
WARN=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

AGENTS=(
  architect auditor bard chancellor concierge
  engineer forager foreman inspector nurse
  quartermaster queen scout supervisor switchboard
  treasurer warden worker
)

pass() { echo -e "  ${GREEN}✅ PASS${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}❌ FAIL${NC} $1"; ((FAIL++)); }
warn() { echo -e "  ${YELLOW}⚠️  WARN${NC} $1"; ((WARN++)); }
section() { echo -e "\n${CYAN}${BOLD}▶ $1${NC}"; }

echo -e "${BOLD}"
echo "============================================================"
echo "  HIVE Verification Test Harness"
echo "  $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
echo -e "${NC}"

# ------------------------------------------------------------
section "1. WORKSPACE STRUCTURE"
# ------------------------------------------------------------
for agent in "${AGENTS[@]}"; do
  ws="$HIVE_ROOT/workspace-$agent"
  if [ -d "$ws" ]; then
    pass "workspace-$agent exists"
  else
    fail "workspace-$agent MISSING at $ws"
  fi
done

# ------------------------------------------------------------
section "2. SOUL.md PRESENT IN EACH WORKSPACE"
# ------------------------------------------------------------
for agent in "${AGENTS[@]}"; do
  soul="$HIVE_ROOT/workspace-$agent/SOUL.md"
  if [ -f "$soul" ]; then
    pass "workspace-$agent/SOUL.md present"
  else
    fail "workspace-$agent/SOUL.md MISSING"
  fi
done

# ------------------------------------------------------------
section "3. HIVE SHARED FILES"
# ------------------------------------------------------------
for f in AGENTS.md HEARTBEAT.md SOUL.md README.md; do
  if [ -f "$HIVE_ROOT/$f" ]; then
    pass "$f present in HIVE root"
  else
    fail "$f MISSING from HIVE root"
  fi
done

if [ -d "$HIVE_ROOT/hive-shared" ]; then
  pass "hive-shared directory exists"
else
  warn "hive-shared directory not found"
fi

# ------------------------------------------------------------
section "4. DATA DIRECTORY STRUCTURE"
# ------------------------------------------------------------
for dir in logs listings waggle archive; do
  target="$DATA_DIR/$dir"
  if [ -d "$target" ]; then
    pass "data/$dir exists"
  else
    warn "data/$dir missing — creating"
    mkdir -p "$target"
  fi
done

if [ -f "$DATA_DIR/research-queue.json" ]; then
  pass "data/research-queue.json exists"
else
  warn "data/research-queue.json missing — creating empty"
  echo "[]" > "$DATA_DIR/research-queue.json"
fi

# ------------------------------------------------------------
section "5. SERVICE CONNECTIVITY"
# ------------------------------------------------------------

# Mosquitto
if nc -z localhost 1883 2>/dev/null; then
  pass "Mosquitto reachable on :1883"
else
  fail "Mosquitto NOT reachable on :1883"
fi

# Chancellor API
CHANCELLOR_RESP=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://localhost:8001/health)
if [ "$CHANCELLOR_RESP" = "200" ]; then
  pass "Chancellor /health → 200 OK"
else
  fail "Chancellor /health → $CHANCELLOR_RESP (expected 200)"
fi

# Chancellor summary
SUMMARY_RESP=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://localhost:8001/summary)
if [ "$SUMMARY_RESP" = "200" ]; then
  pass "Chancellor /summary → 200 OK"
else
  warn "Chancellor /summary → $SUMMARY_RESP"
fi

# Netdata
NETDATA_RESP=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://localhost:19999/api/v1/info)
if [ "$NETDATA_RESP" = "200" ]; then
  pass "Netdata API reachable on :19999"
else
  fail "Netdata NOT reachable on :19999"
fi

# ------------------------------------------------------------
section "6. DOCKER CONTAINERS"
# ------------------------------------------------------------
for container in hive-mosquitto hive-chancellor; do
  STATUS=$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null)
  if [ "$STATUS" = "true" ]; then
    pass "$container running"
  else
    fail "$container NOT running"
  fi
done

# ------------------------------------------------------------
section "7. NUT UPS MONITORING"
# ------------------------------------------------------------
if systemctl is-active --quiet nut-server; then
  pass "nut-server active"
else
  fail "nut-server NOT active"
fi

if systemctl is-active --quiet nut-monitor; then
  pass "nut-monitor active"
else
  fail "nut-monitor NOT active"
fi

UPS_STATUS=$(upsc hive-ups@localhost ups.status 2>/dev/null)
if [ -n "$UPS_STATUS" ]; then
  pass "UPS responding — status: $UPS_STATUS"
else
  warn "UPS status not readable via upsc"
fi

# ------------------------------------------------------------
section "8. HDD MOUNT"
# ------------------------------------------------------------
if mountpoint -q /mnt/hive-storage; then
  pass "/mnt/hive-storage is mounted"
  AVAIL=$(df -h /mnt/hive-storage | awk 'NR==2{print $4}')
  pass "Available space: $AVAIL"
else
  fail "/mnt/hive-storage NOT mounted"
fi

# ------------------------------------------------------------
section "9. AGENTS.md RULE INTEGRITY"
# ------------------------------------------------------------
AGENTS_FILE="$HIVE_ROOT/AGENTS.md"
if grep -q "NEVER DO" "$AGENTS_FILE" 2>/dev/null; then
  pass "AGENTS.md contains NEVER DO rules"
else
  fail "AGENTS.md missing NEVER DO section"
fi

if grep -q "JUST DO IT" "$AGENTS_FILE" 2>/dev/null; then
  pass "AGENTS.md contains JUST DO IT rules"
else
  fail "AGENTS.md missing JUST DO IT section"
fi

if grep -q "OpenRouter" "$AGENTS_FILE" 2>/dev/null; then
  pass "AGENTS.md contains OpenRouter routing rules"
else
  warn "AGENTS.md missing OpenRouter section"
fi

# ------------------------------------------------------------
section "10. ENVIRONMENT CONFIG"
# ------------------------------------------------------------
ENV_FILE="$HIVE_PHASE1/.env"
if [ -f "$ENV_FILE" ]; then
  pass ".env file exists at hive-phase1/.env"
  for var in HIVE_HOST_IP MOSQUITTO_PORT CHANCELLOR_PORT NUT_UPS_NAME HIVE_WORKSPACE_ROOT; do
    if grep -q "^$var=" "$ENV_FILE"; then
      pass ".env contains $var"
    else
      warn ".env missing $var"
    fi
  done
else
  fail ".env file NOT found"
fi

# ------------------------------------------------------------
echo -e "\n${BOLD}============================================================"
echo "  RESULTS"
echo "============================================================${NC}"
echo -e "  ${GREEN}PASS: $PASS${NC}"
echo -e "  ${YELLOW}WARN: $WARN${NC}"
echo -e "  ${RED}FAIL: $FAIL${NC}"
TOTAL=$((PASS + WARN + FAIL))
echo -e "  TOTAL: $TOTAL checks"

if [ $FAIL -eq 0 ]; then
  echo -e "\n  ${GREEN}${BOLD}✅ HIVE IS OPERATIONAL${NC}"
else
  echo -e "\n  ${RED}${BOLD}❌ $FAIL checks failed — review above${NC}"
fi

# Write log
mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/hive-verify-$(date +%Y%m%d-%H%M%S).log"
{
  echo "HIVE Verification Run — $(date)"
  echo "PASS: $PASS | WARN: $WARN | FAIL: $FAIL"
} >> "$LOGFILE"
echo -e "\n  Log written to $LOGFILE"
echo ""
