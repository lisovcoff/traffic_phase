"""Comparable conditional movement marks for fixed offline regime hypotheses.

Condition on an observation having arrived: missing vehicles are not red evidence.
Every regime uses the same mark alphabet and a column-normalized distribution;
giving more movements permission therefore cannot increase every likelihood.
The offline Bernoulli activity rates remain heuristic intensity proxies.
"""
import numpy as np


class MovementMarks:
    def __init__(self, regimes, *, contamination=0.):
        self.vocabulary=sorted({m.replace('_','') for r in regimes for m in r['movement_probabilities']})
        self.parts=[m.split('->') for m in self.vocabulary]
        self.distributions=[];self.cache={}
        for regime in regimes:
            rates={m.replace('_',''):v for m,v in regime['movement_probabilities'].items()}
            matrix=np.array([rates.get(m,[.01]*regime['phase_count']) for m in self.vocabulary],dtype=float)
            matrix=np.maximum(.001,matrix)
            normalized=matrix/matrix.sum(axis=0,keepdims=True)
            self.distributions.append((1-contamination)*normalized+contamination/len(self.vocabulary))

    def likelihoods(self, origin, target):
        key=(origin,target)
        if key not in self.cache:
            indices=[i for i,(a,b) in enumerate(self.parts) if a==origin and (target is None or b==target)]
            self.cache[key]=[matrix[indices].sum(axis=0) for matrix in self.distributions]
        return self.cache[key]
