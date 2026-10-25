import numpy as np
from scripts.transfer_ct_independent_patterns import assign_patterns


def test_source_radius_and_support_reject_queries_without_refitting():
    centers=np.array([[0.,0.],[10.,0.]])
    labels=np.array([0]*5+[1]*4)
    q=np.array([[.5,0.],[2.,0.],[10.,0.]])
    assigned,distance,accepted=assign_patterns(q,centers,labels,np.array([1.,1.]),5)
    np.testing.assert_array_equal(assigned,[0,0,1])
    np.testing.assert_allclose(distance,[.5,2,0])
    np.testing.assert_array_equal(accepted,[True,False,False])
