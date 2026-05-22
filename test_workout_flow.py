"""Step 1-4: Create run workout, schedule, verify, cleanup."""
import asyncio, json, sys
sys.path.insert(0, "C:/coros-mcp/coros-mcp-main")
from dotenv import load_dotenv
import os
load_dotenv(os.path.join(os.path.dirname("C:/coros-mcp/coros-mcp-main/server.py"), ".env"))

import coros_api
import httpx

WORKOUT_NAME = "验证_%HRR_Z2"
HAPPEN_DAY = "20260517"

async def main():
    auth = await coros_api.try_auto_login()
    if not auth:
        print("ERROR: Login failed")
        return

    # --- Pre-cleanup ---
    raw = await coros_api.fetch_schedule(auth, HAPPEN_DAY, HAPPEN_DAY)
    for p in raw.get("programs", []):
        if p.get("name") == WORKOUT_NAME:
            pid = p.get("idInPlan")
            for e in raw.get("entities", []):
                if str(e.get("idInPlan", "")) == str(pid):
                    await coros_api.remove_scheduled_workout(auth, raw["id"], pid, e.get("planProgramId") or None)
                    break
    for w in await coros_api.fetch_workouts(auth):
        if isinstance(w, dict) and w.get("name") == WORKOUT_NAME:
            await coros_api.delete_workout(auth, w["id"])

    # === Step 1: Create ===
    workout_id = await coros_api.create_run_workout(
        auth, WORKOUT_NAME,
        [{"name": "10:00 Z2", "duration_minutes": 10, "hr_low": 2}],
        sport_type=1, hr_type=2, intensity_type=2, value_type=None
    )
    print(f"1. CREATE: workout_id={workout_id}")

    # === Step 2: Schedule ===
    await coros_api.schedule_workout(auth, workout_id, HAPPEN_DAY)
    print(f"2. SCHEDULE: {HAPPEN_DAY}")

    # === Step 3: Read back (raw API) ===
    params = {"startDate": HAPPEN_DAY, "endDate": HAPPEN_DAY, "supportRestExercise": 1}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            coros_api._base_url(auth.region) + coros_api.ENDPOINTS["schedule"],
            params=params, headers=coros_api._auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()
    raw_data = body.get("data", {})

    # Debug: check programs structure
    programs = raw_data.get("programs", [])
    print(f"3. RAW: {len(programs)} programs")
    for i, p in enumerate(programs[:3]):
        print(f"   prog[{i}] keys: {list(p.keys())[:15]}, has 'name': {'name' in p}")

    # Find our program - some programs might not have 'name'
    prog = None
    for p in programs:
        if p.get("name") == WORKOUT_NAME:
            prog = p
            break

    if not prog:
        # maybe name is encoded differently
        for p in programs:
            nm = p.get("name", "")
            print(f"   name: {repr(nm[:50])}")
        print("FAIL: program not found")
        return

    ent = next((e for e in raw_data.get("entities", []) if str(e.get("idInPlan")) == str(prog["idInPlan"])), None)
    print(f"   idInPlan={prog['idInPlan']}")

    # === VERIFICATION ===
    ref = prog.get("referExercise", {})
    ex0 = prog["exercises"][0]
    results = [
        ("referExercise.valueType", ref.get("valueType"), 2),
        ("referExercise.hrType", ref.get("hrType"), 2),
        ("referExercise.intensityType", ref.get("intensityType"), 2),
        ("exercises[0].intensityPercent", ex0.get("intensityPercent"), 59000),
        ("exercises[0].intensityValue", ex0.get("intensityValue"), 142),
        ("exercises[0].isIntensityPercent", ex0.get("isIntensityPercent"), True),
    ]
    all_ok = True
    print("\n=== RESULTS ===")
    for label, actual, expected in results:
        ok = actual == expected
        all_ok = all_ok and ok
        print(f"  {label} = {actual} {'OK' if ok else 'FAIL (expected ' + str(expected) + ')'}")

    # === Step 4: Cleanup ===
    plan_id = raw_data["id"]
    id_in_plan = prog["idInPlan"]
    await coros_api.remove_scheduled_workout(auth, plan_id, id_in_plan, ent.get("planProgramId") or None if ent else None)
    await coros_api.delete_workout(auth, workout_id)
    print(f"\n4. CLEANUP: done")

    print(f"\n>>> {'ALL PASSED' if all_ok else 'SOME FAILED'} <<<")

asyncio.run(main())
