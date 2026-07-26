#!/usr/bin/env python3
"""앨범 임베딩 생성 → Neo4j vector index (유사검색·추천용).

텍스트 = 아티스트 + 앨범 + 장르 + 대표곡 + 해설 (있는 것만 결합).
모델 기본값은 다국어 경량 모델(한국어 지원). CPU로 수분 내 완료.

사용: python scripts/build_embeddings.py [--model NAME] [--batch 64]
"""
from __future__ import annotations

import argparse
import os
import sqlite3

from neo4j import GraphDatabase

DB = os.path.expanduser(os.environ.get("MW_DB", "~/music-wiki-vault/music-wiki.db"))
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "musicwiki"))
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"  # 384d


def text_of(r) -> str:
    bits = [r["artist"], r["album"], r["genre"]]
    if r["rep"]:
        bits.append(f"대표곡: {r['rep']}")
    if r["description"]:
        bits.append(r["description"])
    return " · ".join(str(b) for b in bits if b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--device", default=os.environ.get("MW_EMBED_DEVICE", "cpu"),
                    help="cpu(기본, ser8과 동일) 또는 cuda")
    args = ap.parse_args()

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute("SELECT * FROM catalog")]
    texts = [text_of(r) for r in rows]
    print(f"· 대상 {len(rows)}건, 모델 {args.model} ({args.device}) 로드 중…", flush=True)

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(args.model, device=args.device)
    dim = model.get_sentence_embedding_dimension()
    vecs = model.encode(texts, batch_size=args.batch, normalize_embeddings=True,
                        show_progress_bar=True)
    print(f"· 임베딩 {vecs.shape} 완료", flush=True)

    drv = GraphDatabase.driver(URI, auth=AUTH)
    with drv.session() as s:
        s.run("CREATE VECTOR INDEX album_embedding IF NOT EXISTS "
              "FOR (a:Album) ON (a.embedding) "
              "OPTIONS {indexConfig: {`vector.dimensions`: $d, "
              "`vector.similarity_function`: 'cosine'}}", d=dim)
        payload = [{"key": r["key"], "v": v.tolist()} for r, v in zip(rows, vecs)]
        for i in range(0, len(payload), 200):
            s.run("UNWIND $rows AS r MATCH (a:Album {key:r.key}) "
                  "CALL db.create.setNodeVectorProperty(a, 'embedding', r.v)",
                  rows=payload[i:i + 200])
        n = s.run("MATCH (a:Album) WHERE a.embedding IS NOT NULL "
                  "RETURN count(a) AS n").single()["n"]
        print(f"· Neo4j 벡터 적재 {n}건 (dim={dim})")
    drv.close()


if __name__ == "__main__":
    main()
