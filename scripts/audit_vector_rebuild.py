"""Compare a local Milvus candidate with freshly parsed documents and graph rounds."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

from pymilvus import MilvusClient
from scripts.evaluate_fair_retrieval import digest, write_json
from scripts.seed_knowledge import _round_content


def audit(graph, documents, collection):
    expected = [json.loads(line) for line in documents.read_text().splitlines()]
    fields = sorted(expected[0])
    client = MilvusClient(uri='http://localhost:19530')
    count = client.query(collection,filter='',output_fields=['count(*)'],consistency_level='Strong')[0]['count(*)']
    # ponytail: this local corpus is under Milvus's 16,384-row query limit; use query_iterator when it grows.
    actual = client.query(collection,filter='',output_fields=fields,limit=16383,consistency_level='Strong')
    def canonical(rows):
        return sorted(json.dumps({k:r[k] for k in fields},sort_keys=True,ensure_ascii=False) for r in rows)
    round_docs = {(r['match_id'],r['map'],r['round_number']):r for r in actual if r['tactic_type']=='Round Event Evidence'}
    errors=[]
    with sqlite3.connect(graph.resolve().as_uri()+'?mode=ro',uri=True) as db:
        keys=set()
        for mid,map_name,number,props in db.execute("SELECT match_id,map_name,round_number,properties FROM nodes WHERE node_type='round'"):
            key=(mid,map_name,number);keys.add(key)
            parsed=json.loads(props) | {'round_number':number}
            groups={'kill':'kills','grenade':'grenades','flash':'flash_blinds','plant':'plants'}
            for group in groups.values(): parsed[group]=[]
            events=db.execute("SELECT node_id,properties FROM nodes WHERE node_type='event' AND match_id=? AND map_name=? AND round_number=?",key).fetchall()
            for _,p in sorted(events,key=lambda x:int(x[0].rsplit(':',1)[1])):
                p=json.loads(p);parsed[groups[p['kind']]].append(p)
            if key not in round_docs or round_docs[key]['text'] != _round_content(map_name,parsed):
                errors.append(list(key))
    actual_lines=canonical(actual)
    exact=actual_lines==canonical(expected)
    return {'version':'vector-rebuild-v2','collection':collection,'graph_sha256':digest(graph),
            'documents_sha256':digest(documents),'audit_source_sha256':digest(__file__),
            'document_renderer_sha256':digest(Path(__file__).with_name('seed_knowledge.py')),
            'content_sha256':hashlib.sha256('\n'.join(actual_lines).encode()).hexdigest(),
            'count':count,'types':dict(Counter(r['tactic_type'] for r in actual)),
            'exact_document_match':exact,'graph_round_keys_match':set(round_docs)==keys,
            'graph_round_content_errors':errors,'remote_model_calls':0,
            'passed':count==len(actual)==len(expected) and exact and set(round_docs)==keys and not errors}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graph',type=Path,required=True)
    p.add_argument('--documents',type=Path,required=True)
    p.add_argument('--collection',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    report=audit(args.graph,args.documents,args.collection)
    write_json(args.output,report)
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)
