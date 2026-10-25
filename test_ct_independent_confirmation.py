import numpy as np
import pytest
from scripts.evaluate_ct_independent_confirmation import confirmation_interval


def test_balanced_map_interval_uses_series_and_handles_degenerate_variance():
    rows=[{'series':f'{m}_{i}','map':str(m),'graph_gru':float(np.exp(-.1+delta)),'mlp_gru':1.0}
          for m in range(6) for i,delta in enumerate((-.01,.01))]
    result=confirmation_interval(rows)
    assert result['log_ratio']==pytest.approx(-.1)
    assert result['SE']==pytest.approx(np.sqrt(.0002/12))
    assert result['Welch_Satterthwaite_df']==pytest.approx(6)
    for row in rows:row['graph_gru']=1.0
    assert confirmation_interval(rows)['degenerate_observed_residual_variance']
    with pytest.raises(AssertionError):confirmation_interval(rows[:-1])
