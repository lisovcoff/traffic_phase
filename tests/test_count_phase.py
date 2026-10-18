import numpy as np
from app.core.count_phase import circular_partition,local_history


def test_count_partition_finds_two_unequal_movement_compositions_without_k_input():
    counts=np.zeros((100,2));counts[:20,0]=10;counts[20:,1]=10
    groups,candidates=circular_partition(counts,100.)
    assert len(groups)==2
    assert sorted(round(g['duration']) for g in groups)==[20,80]


def test_local_count_history_retains_empty_time_and_observed_extent():
    x=np.zeros((200,2));x[5:15,0]=5;x[40:75,1]=5;x[105:115,0]=5;x[140:175,1]=5
    rows=local_history(x,np.array([[.99,.01],[.01,.99]]),[20,80],100)
    assert rows[0][0]==0 and rows[-1][1]==200
    assert all(a[1]==b[0] for a,b in zip(rows,rows[1:]))
    assert all(len(row)==3 for row in rows)


def test_single_composition_does_not_fabricate_two_phases():
    groups,_=circular_partition(np.ones((100,2)),100.)
    assert len(groups)==1
