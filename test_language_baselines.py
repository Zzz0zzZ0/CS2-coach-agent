import pytest
from tokenizers import Tokenizer,models,pre_tokenizers
from scripts.evaluate_language_baselines import lexical_index,lexical_rank,lexical_tokens,rrf


def test_bm25_scope_and_rare_fact_order():
    texts=['Alpha plant bomb smoke','Alpha smoke','Cedar plant bomb']
    db=lexical_index(texts)
    assert lexical_rank(db,'Alpha plant bomb',[0,1])[0]==0
    assert lexical_rank(db,'Alpha',[2])==[]
    assert lexical_rank(db,'Alpha',[])==[]
    db.close()


def test_subword_round_trip_no_raw_chinese_token_merge():
    t=Tokenizer(models.WordLevel({'[UNK]':0,'首':1,'杀':2,'补':3,'枪':4}))
    t.pre_tokenizer=pre_tokenizers.Split('',behavior='isolated')
    assert lexical_tokens('首杀',t)==['v1','v2']
    db=lexical_index(['首杀','补枪'],t)
    assert lexical_rank(db,'首杀',[0,1],t)==[0]
    db.close()


def test_full_rank_rrf_ties_and_unique_sources():
    assert rrf([0,1,2],[2,1,0])==[0,2,1]
    assert rrf([],[])==[]
