import copy

import numpy as np
import pytest

from scripts.calibrate_fair_retrieval import alias_entities, check_pairs, expand_query, summarize
from scripts.evaluate_fair_retrieval import build_index, ranks
from test_fair_retrieval import sample


def test_exact_alias_equivalence_preserves_scope_and_applies_to_all_methods():
    docs,dataset=sample();docs[1]['entities']=['team bravo']
    before=copy.deepcopy(docs)
    adapted=alias_entities(docs,{'bravo':['bravo','team bravo']})
    query={**dataset['cases'][0],'query':'bravo opening kill','entities':['bravo']}
    db=build_index(docs)
    vectors=np.array([[1.0,0],[0.1,0],[2.0,0]])
    raw,_=ranks(db,docs,query,True,np.array([1,0]),vectors,1)
    normalized,_=ranks(db,adapted,query,True,np.array([1,0]),vectors,1)
    assert all(v==[] for v in raw.values())
    assert all(v==[1] for v in normalized.values())
    assert docs==before and adapted[1]['text']==docs[1]['text']
    academy=[{**docs[1],'entities':['team bravo academy']}]
    assert 'bravo' not in alias_entities(academy,{'bravo':['bravo','team bravo']})[0]['entities']
    with pytest.raises(ValueError,match='Overlapping'):
        alias_entities(docs,{'a':['a','shared'],'b':['b','shared']})
    db.close()


def test_glossary_preserves_query_identity_and_does_not_translate_english():
    glossary={'下包':'bomb plant','炸弹安放':'bomb plant','回合':'round'}
    query='找出 MissingPlayer 的下包回合以及炸弹安放记录'
    adapted=expand_query(query,glossary)
    assert adapted==query+' bomb plant round'
    assert expand_query('MissingPlayer bomb plant rounds',glossary)=='MissingPlayer bomb plant rounds'


def test_pair_contract_and_summary_never_count_translations_as_independent_samples():
    base={'semantic_group':'g','filters':{'map':'Nuke'},'entities':[],'event_kind':'kill'}
    dataset={'cases':[{**base,'id':'en','language':'en'},{**base,'id':'zh','language':'zh'}]}
    assert len(check_pairs(dataset,{'en':{'r':3},'zh':{'r':3}}))==1
    with pytest.raises(ValueError,match='relevance'):
        check_pairs(dataset,{'en':{'r':3},'zh':{}})
    rows=[{'configuration':'raw_exact','method':'bm25','entity_constraint':True,
           'language':lang,'semantic_group':'g','metrics':{'ndcg_at_k':value,'recall_at_k':value,'false_retrieval':None,'false_abstention':False}}
          for lang,value in [('en',1.0),('zh',0.0)]]
    result=next(x for x in summarize(rows) if x['method']=='bm25' and x['entity_constraint'] and x['language']=='paired_macro')
    assert result['quality']['ndcg_at_k']=={'mean':0.5,'n_semantic_groups':1}
