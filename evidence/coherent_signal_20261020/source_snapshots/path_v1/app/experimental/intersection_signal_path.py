"""Default-off raw-packet adapter for a coherent, committed signal path.

Uses the joint filter's emissions; neither videos nor lamp labels are inputs.
Instantaneous and delayed reconstructed heads have explicitly different fields.
"""
from copy import deepcopy
from app.core.intersection_signal_filter import CoherentIntersection
from app.core.intersection_signal_path import SignalPath


class PathIntersection:
    def __init__(self,model,*,history_lag_s=10):
        self.engine=CoherentIntersection(model,history_lag_s=0)
        self.path=SignalPath(self.engine.filter,history_lag_s)
        self.latest=None
        def observation(now,predicted_g,predicted_e,current_g,current_e,evidence_ms):
            self.latest=self.path.update(now,predicted_g,predicted_e,current_g,current_e)
            return None
        self.engine.filter.smoother.push=observation

    def ingest(self,packet):
        result=self.engine.ingest(packet);heads=deepcopy(self.latest['heads'])
        recent=result['status']=='TRACKING'
        for a,head in heads.items():
            for lamp in [head['main']]+head['arrows']:
                lamp.update(confidence=None,source='JOINT_PATH_POINT_ESTIMATE_UNCALIBRATED')
                if not recent:lamp['state']='UNKNOWN'
        history=deepcopy(self.latest['history'])
        if history is not None:
            # No calibrated confidence is fabricated for the committed path.
            for head in history['heads'].values():
                for lamp in [head['main']]+head['arrows']:lamp.update(confidence=None,source='COMMITTED_JOINT_PATH')
        result.update(heads=heads,schema='experimental-joint-path-v1',
            estimate_kind='PROVISIONAL_JOINT_PATH',finalized_history=[] if history is None else [history],
            history_lag_s=self.path.lag_s,phase_metadata_basis='FILTER_MARGINALS_NOT_PATH_STATE',
            production_enabled=False)
        return result
