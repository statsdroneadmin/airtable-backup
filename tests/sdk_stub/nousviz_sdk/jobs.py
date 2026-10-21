STATE = {"cancel_after": None, "checks": 0, "beats": 0, "last": None, "run_id": None}
def _set_current_run_id(rid):
    STATE["run_id"] = rid
def heartbeat(progress=None):
    STATE["beats"] += 1; STATE["last"] = progress
def check_cancelled():
    STATE["checks"] += 1
    ca = STATE["cancel_after"]
    return ca is not None and STATE["checks"] > ca
def get_run_id():
    return STATE["run_id"]
