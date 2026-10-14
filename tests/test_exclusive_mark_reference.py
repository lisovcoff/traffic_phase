import inspect
from scripts.exclusive_mark_reference import reference


def ref(points, k=3, coverage=((0, 100),)):
    return reference([{'timestamp_ms': t, 'movement': str(z)} for t, z in points],
                     {str(z): z for z in range(k)}, list(range(k)), coverage)


def test_exclusive_marks_rounding_and_wrap():
    r = ref([(1000, 2), (2000, 2), (5000, 0)])
    assert r['edges'][0]['interval_ms'] == [1999.5, 5000.5]
    assert r['edges'][0]['status'] == 'conditional_bracket'
    assert r['status'] == 'ambiguous'  # order alone cannot exclude extra cycles


def test_no_events_and_single_mark():
    assert ref([])['reason'] == 'NO_EVENTS'
    assert ref([(1000, 0), (90000, 0)])['edges'] == []
    assert ref([(1000, 0)])['endpoint_boundaries'] == 'unavailable'


def test_missing_observed_phase():
    edge = ref([(1000, 0), (9000, 2)])['edges'][0]
    assert edge['reason'] == 'UNOBSERVED_INTERMEDIATE_PHASE'
    assert edge['minimum_transitions'] == 2


def test_observation_gap():
    assert ref([(1000, 0), (9000, 1)], coverage=((0, 2), (8, 10)))['edges'][0]['reason'] == 'OBSERVATION_GAP'


def test_equal_timestamps_not_unique_boundary():
    assert ref([(1000, 0), (1000, 1)])['edges'][0]['reason'] == 'TIMESTAMP_ORDER_UNRESOLVED'


def test_truth_free_interface_and_renaming():
    assert list(inspect.signature(reference).parameters) == ['events', 'mapping', 'order', 'coverage', 'resolution_ms']
    assert reference([{'timestamp_ms': 1000, 'movement': 'east'}], {'east': 0}, [0, 1], [[0, 10]]) == ref([(1000, 0)], k=2, coverage=((0, 10),))
