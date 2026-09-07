from scripts.prepare_isolated_relation_pilot import choose


def test_no_near_miss_records_missing_quotas_instead_of_easy_negatives():
    cases,missing=choose([{'id':'empty','events':[]}],{'One':'1','Two':'2'},'sample','Mirage')
    assert cases==[] and len(missing)==6
    assert {x['polarity'] for x in missing}=={'positive','negative'}
