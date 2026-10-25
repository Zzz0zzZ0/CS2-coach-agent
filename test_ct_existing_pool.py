import numpy as np
import pytest

from scripts.evaluate_ct_existing_pool import rated_pool_ndcg


def test_rated_pool_does_not_treat_zero_missing_or_singletons_as_validation():
    assert rated_pool_ndcg([0, 1], [3, 0], [4, 5])['ndcg5_within_rated_pool'] == 1
    reverse = rated_pool_ndcg([1, 0], [3, 0], [4, 5])
    assert reverse['ndcg5_within_rated_pool'] == pytest.approx(1 / np.log2(3))
    assert rated_pool_ndcg([0, 1], [0, 0], [4, 5]) is None
    assert rated_pool_ndcg([0], [3], [4]) is None
    assert rated_pool_ndcg([1, 1], [0, 3], [5, 4])['ndcg5_within_rated_pool'] == 1
    with pytest.raises(ValueError):
        rated_pool_ndcg([0, 1], [None, 3], [4, 5])
