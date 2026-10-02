# V9 anomaly test plan

This file records the next validation scenarios for V9/V10. They test reconstructed timing patterns, not direct lamp telemetry.

## Public-source findings

FHWA documents ordinary green extension from vehicle actuations up to a configured maximum green. It also documents emergency-vehicle preemption and priority, where the controller may hold a current green, transfer right-of-way, or alter the normal phase sequence.

FHWA also describes detector failure modes. A continuous detector call can make a phase reach maximum green repeatedly. A failure without a call can lead to an omitted phase or a maximum-recall fallback. Signal controllers can also operate in flashing mode during malfunction handling or as a scheduled mode.

## Synthetic scenarios

### 1. One-cycle green extension

Take a stable reference model and extend one phase by +N seconds in one or two cycles.

Offline:
- normal cycles should stay close to the learned baseline;
- the anomalous cycle should be surfaced as a temporary phase extension;
- the reported delta should be approximately +N seconds, subject to sparse vehicle evidence.

Online:
- the causal tracker should move away from the periodic baseline;
- schedule_shift_s should become positive during the extension;
- interpretation should become temporary_phase_extension_or_delay when the shift crosses the current threshold.

The algorithm must not claim that the cause was a fire truck. Emergency preemption and ordinary demand extension can have overlapping timing signatures.

### 2. Demand-driven maximum green

Generate several high-demand cycles where repeated actuations keep a phase active until maximum green.

This tests the distinction between a one-off temporary extension and a repeated or persistent timing change.

### 3. Detector stuck-on

Create a continuous artificial demand on one phase.

Expected signature: repeated maximum-length service. This is a detector/controller failure pattern, not just a traffic spike.

### 4. Detector stuck-off / omitted phase

Remove evidence for a movement that normally requests a phase.

Expected result: test whether the phase is shortened or omitted without inventing a new phase. Lack of vehicle evidence is not direct proof that the signal was red.

### 5. Lane closure

Remove or strongly reduce one movement stream while keeping the underlying signal schedule unchanged.

Expected result: traffic-flow change with a stable phase template. This is important for the real lane-closure dataset.

### 6. Emergency preemption / priority

For one or two cycles, hold green on the emergency approach, shorten conflicting service, or replace part of the normal sequence.

Expected result: temporary timing deviation; cause remains unknown unless external metadata is supplied.

## Critical interpretation rule

There is no direct ground-truth lamp telemetry in the current project. Outputs therefore remain inferred, estimated, or reconstructed. A detected green extension means the traffic timing pattern deviated from the learned baseline; it does not prove why that happened.

The first implementation target is a synthetic reference-plus-perturbation benchmark, followed by replay of the perturbed events through the stateful FastAPI realtime endpoint.
