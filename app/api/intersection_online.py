"""Per-second partial-vehicle JSON on an exclusively offline-learned structure."""
from typing import Annotated
from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,ConfigDict,Field,StrictInt,FiniteFloat

from app.api.intersection_projects import _folder
from app.core import intersection_online_store as store
from app.core.intersection_project import load_prediction,read_model

router=APIRouter(prefix='/api/v1/intersections',tags=['causal intersection online'])


class LiveDetection(BaseModel):
    model_config=ConfigDict(extra='ignore',strict=True)
    millis:Annotated[StrictInt,Field(ge=0)]
    centroid_x:FiniteFloat|None=None
    centroid_y:FiniteFloat|None=None
    speed:Annotated[FiniteFloat,Field(ge=0)]|None=None
    lat:Annotated[FiniteFloat,Field(ge=-90,le=90)]|None=None
    lng:Annotated[FiniteFloat,Field(ge=-180,le=180)]|None=None
    zone:str|None=None


class LiveVehicle(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str|StrictInt
    zone_in:str
    detections:Annotated[list[LiveDetection],Field(min_length=1,max_length=2000)]


class LivePacket(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sequence:Annotated[StrictInt,Field(ge=0)]
    timestamp_ms:Annotated[StrictInt,Field(ge=0)]
    vehicles:Annotated[list[LiveVehicle],Field(max_length=5000)]


def _invoke(fn,*args):
    try:return fn(*args)
    except KeyError as e:raise HTTPException(404,str(e)) from e
    except ValueError as e:raise HTTPException(409,str(e)) from e


@router.post('/{identifier}/online',status_code=201)
def create(identifier:str):return _invoke(store.create_stream,_folder(identifier))


@router.post('/{identifier}/online/{stream}/packets')
def ingest(identifier:str,stream:str,packet:LivePacket):
    value=packet.model_dump()
    if sum(len(v['detections']) for v in value['vehicles'])>100000:raise HTTPException(413,'packet detection budget exceeded')
    return _invoke(store.accept_packet,_folder(identifier),stream,value)


@router.get('/{identifier}/online/{stream}')
def latest(identifier:str,stream:str):return _invoke(store.latest_snapshot,_folder(identifier),stream)


@router.get('/{identifier}/online/{stream}/history')
def history(identifier:str,stream:str,after:int=Query(-1,ge=-1),limit:int=Query(1000,ge=1,le=1000)):
    return _invoke(store.stream_history,_folder(identifier),stream,after,limit)


@router.get('/{identifier}/online/{stream}/at')
def at(identifier:str,stream:str,timestamp_ms:int=Query(ge=0)):
    return _invoke(store.snapshot_at,_folder(identifier),stream,timestamp_ms)


@router.get('/{identifier}/online/{stream}/viewer',response_class=HTMLResponse)
def viewer(identifier:str,stream:str):
    folder=_folder(identifier);_invoke(store.latest_snapshot,folder,stream)
    model=read_model(folder);session=model['sessions'][0]
    _,_,result=load_prediction(folder,session['session_id'])
    from app.core.observed_topology import project_observed_topology
    from scripts.v9_spatial_visualizer import render_html
    result=project_observed_topology(result,model['approaches'],repair_missing_phases=(
        'selective' if model.get('projection_version')=='observed-topology-v3' else model.get('projection_version')=='observed-topology-v2'))
    result.get('event_extraction',{}).pop('temporal_events',None)
    projection=model['geometries'][session['source_member']]['projection']
    page=render_html(result,projection,[],intersection_profile='none',online_mode=True)
    return page.replace('V9 — пространственная реконструкция перекрёстка','Перекрёсток — онлайн')
