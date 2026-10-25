import numpy as np
from scripts.retrieve_ct_independent_context import cross_observation_distances
from scripts.evaluate_ct_reconstruction import observation_distances


def test_cross_distance_matches_frozen_joint_metric_including_whole_window_permutations():
    rng=np.random.default_rng(3)
    alive=np.ones((3,5,5),dtype=bool)
    pairs=alive[:,:,:,None]&alive[:,:,None,:]&~np.eye(5,dtype=bool)
    edges=rng.normal(size=(3,5,5,5,3));edges=(edges+edges.transpose(0,1,3,2,4))/2
    data={'nodes':rng.normal(size=(3,5,5,15)),'node_mask':alive,
          'node_feature_mask':np.ones((3,5,5,15),dtype=bool),'pair_mask':pairs,
          'edges':edges*pairs[...,None]}
    expected=observation_distances(data)
    result=cross_observation_distances({k:v[:1] for k,v in data.items()},{k:v[1:] for k,v in data.items()})
    np.testing.assert_allclose(result,expected[:1,1:],atol=1e-12)
