"""Versioned online engine selection with deterministic legacy restoration."""
from app.core.intersection_online import CausalIntersection,VERSION as LEGACY_VERSION
from app.experimental.intersection_change_point import ChangePointTimingIntersection

VERSION='causal-intersection-v8'
SUPPORTED_VERSIONS=(LEGACY_VERSION,VERSION)


class AdaptiveIntersection(ChangePointTimingIntersection):
    """Joint color estimates, local motion and competing duration programs."""
    VERSION=VERSION

    def _summarize(self,base,results,q,blocked):
        result=super()._summarize(base,results,q,blocked)
        result['production_enabled']=True
        return result


def recommended_version(model):
    # Old saved models can still replay their original engine. A fresh offline
    # analysis automatically learns this geometry; no operator scheme is needed.
    return VERSION if model.get('queue_observations',{}).get('references') else LEGACY_VERSION


def create_engine(model,version):
    if version==LEGACY_VERSION:return CausalIntersection(model)
    if version==VERSION:return AdaptiveIntersection(model)
    raise ValueError('unsupported stream engine; original history is preserved')
