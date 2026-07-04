#!/usr/bin/env bash
# List WA counties with parcels and Phase B readiness (Droplet ops).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env)
"${COMPOSE[@]}" exec -T worker python -c "
from app.config import get_settings
from app.db import SessionLocal
from app.wa_phase_b_rollout import load_phase_b_config, phase_b_status_summary
from app.wa_statewide_rollout import load_rollout_config

s = get_settings()
pb = load_phase_b_config(s.wa_phase_b_rollout_config_path)
pr = load_rollout_config(s.wa_statewide_rollout_config_path)
db = SessionLocal()
try:
    st = phase_b_status_summary(
        db,
        config=pb,
        pilot_config_path=s.pilot_config_path,
        parcel_rollout_config=pr,
        rollout_enabled=s.wa_phase_b_rollout_enabled,
        redis_url=s.redis_url,
    )
    print('next', st.get('next_county_fips'))
    print('cooldown_ready', st.get('cooldown_ready'), 'last_merged', st.get('last_merged_county_fips'))
    ready = [c for c in (st.get('counties') or []) if c.get('ready')]
    blocked = [c for c in (st.get('counties') or []) if not c.get('ready') and c.get('parcels_in_db', 0) > 0]
    print('ready_count', len(ready))
    for c in ready[:12]:
        print(' READY', c['county_fips'], c.get('parcels_missing_zoning'), 'missing')
    no_builder = [c for c in blocked if c.get('skip_reason') == 'no_overlay_builder_or_staged_file']
    print('needs_gis_source', len(no_builder))
    for c in no_builder[:8]:
        print(' NO_BUILDER', c['county_fips'], c.get('parcels_in_db'), 'parcels')
finally:
    db.close()
"
