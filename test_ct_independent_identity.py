import pytest
from scripts.verify_ct_independent_identities import match_rosters


def test_identity_requires_all_five_unique_names_not_just_similar_team_tags():
    native={'pv':['a','b','c','d','e'],'tl':['f','g','h','i','j']}
    public={'parivision':['e','b','a','d','c'],'liquid':['j','i','h','g','f']}
    assert match_rosters(native,public)=={'pv':'parivision','tl':'liquid'}
    public['liquid'][-1]='substitute'
    with pytest.raises(AssertionError,match='unresolved'):match_rosters(native,public)
    assert match_rosters({'x':[' NAF-FLY','a','b','c','d'],'y':['Techno4K','f','g','h','i']},
                         {'liquid':['naf','a','b','c','d'],'mongolz':['techno','f','g','h','i']})=={'x':'liquid','y':'mongolz'}
