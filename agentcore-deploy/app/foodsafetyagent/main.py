from __future__ import annotations
import importlib.util, os, sys, boto3

_HERE = os.path.dirname(os.path.abspath(__file__))
for _t in ["find_restaurants","get_safety_score","explain_restaurant"]:
    _p = os.path.join(_HERE, _t)
    if _p not in sys.path: sys.path.insert(0, _p)

os.environ.setdefault("SCORES_JSON_PATH",   "/tmp/scores.json")
os.environ.setdefault("HISTORY_JSON_PATH",  "/tmp/inspection_history.json")
os.environ.setdefault("SAGEMAKER_USE_STUB", "true")
os.environ.setdefault("DATA_BUCKET_REGION", "us-east-1")
os.environ.setdefault("DATA_BUCKET",        "food-safety-intelligence-data")
os.environ.setdefault("DATA_PREFIX",        "web-app-data")

_data_ready = False

def _warm():
    global _data_ready
    if _data_ready:
        return
    import logging as _log
    _logger = _log.getLogger("foodsafety._warm")
    bucket = os.environ.get("DATA_BUCKET", "food-safety-intelligence-data")
    prefix = os.environ.get("DATA_PREFIX", "web-app-data")
    configured_region = os.environ.get("DATA_BUCKET_REGION", "us-east-1")
    files = [
        (os.environ.get("SCORES_JSON_PATH",  "/tmp/scores.json"),  f"{prefix}/scores.json"),
        (os.environ.get("HISTORY_JSON_PATH", "/tmp/inspection_history.json"), f"{prefix}/inspection_history.json"),
    ]
    # Build region list: try configured region first, then fallbacks.
    regions_to_try: list = [configured_region]
    for r in ("us-east-1", "us-west-2", None):
        if r not in regions_to_try:
            regions_to_try.append(r)
    last_error = None
    for region in regions_to_try:
        try:
            s3 = boto3.client("s3", region_name=region) if region else boto3.client("s3")
            _logger.info(f"[warm] trying region={region} bucket={bucket}")
            for local, key in files:
                if not os.path.exists(local):
                    _logger.info(f"[warm] downloading s3://{bucket}/{key} → {local}")
                    resp = s3.get_object(Bucket=bucket, Key=key)
                    with open(local, "wb") as fh:
                        fh.write(resp["Body"].read())
                    _logger.info(f"[warm] downloaded {local}: {os.path.getsize(local)} bytes")
            _data_ready = True
            _logger.info("[warm] data ready")
            return
        except Exception as e:
            _logger.error(f"[warm] region={region} failed: {type(e).__name__}: {e}")
            last_error = e
            continue
    # S3 unavailable — agent continues with stub scores and no pre-computed data.
    _logger.warning(f"[warm] S3 download failed in all regions (last: {last_error}). "
                    "Running without pre-computed scores; stub model still active.")
    _data_ready = True

def _load(name):
    path = os.path.join(_HERE, name, "handler.py")
    spec = importlib.util.spec_from_file_location(f"_{name}", path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

_find = _load("find_restaurants")
_score = _load("get_safety_score")
_explain = _load("explain_restaurant")

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from model.load import load_model

app = BedrockAgentCoreApp()
log = app.logger

@tool
def find_restaurants(neighborhood:str="",lat:float=0.0,lon:float=0.0,radius_km:float=1.0,cuisine:str="",limit:int=20)->list:
    """Find restaurants near a Chicago neighborhood using OpenStreetMap. Call this first."""
    ev={"radius_km":radius_km,"limit":limit}
    if neighborhood: ev["neighborhood"]=neighborhood
    if lat and lon:  ev["lat"]=lat; ev["lon"]=lon
    if cuisine:      ev["cuisine"]=cuisine
    return _find.handler(ev, None)

@tool
def get_safety_score(restaurants:list)->list:
    """Score restaurants using the XGBoost model. Call after find_restaurants."""
    return _score.handler({"restaurants":restaurants}, None)

@tool
def explain_restaurant(license_id:str)->dict:
    """Get full SHAP drivers and inspection history for one restaurant by license_id."""
    return _explain.handler({"license_id":license_id}, None)

SYSTEM_PROMPT = open(os.path.join(_HERE, "system_prompt.txt")).read()
_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = Agent(model=load_model(), system_prompt=SYSTEM_PROMPT,
                       tools=[find_restaurants, get_safety_score, explain_restaurant])
    return _agent

@app.entrypoint
async def invoke(payload, context):
    log.info("Food Safety Agent invoked")
    _warm()
    query = payload.get("query") or payload.get("prompt","")
    if not query:
        yield "Error: query field is required"; return
    async for event in get_agent().stream_async(query):
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]

if __name__ == "__main__":
    app.run()
