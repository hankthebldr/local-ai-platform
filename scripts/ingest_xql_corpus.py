#!/usr/bin/env python3
# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ingest_xql_corpus — One-shot ingestion of docs/seed/xql/ into a dedicated
ChromaDB collection (`xql_corpus`) for retrieval by XQL/XDM authoring
agents.

Walks the mirrored gocortex-xql-ide corpus, chunks each file via the
project's Chunker, embeds via the project's EmbeddingService, and stores
chunks in a sibling collection alongside the user-uploaded
`enclave-docs` collection.

Idempotent: re-running with --reset drops and recreates the collection
before re-ingesting; otherwise it skips files whose content hash already
appears in the collection's metadata.

Usage:
    python scripts/ingest_xql_corpus.py [--reset] [--dry-run]
                                        [--corpus-dir docs/seed/xql]
                                        [--collection xql_corpus]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Ensure repo root on sys.path so `api.*` imports work when run from /scripts
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from api.services.chunker import Chunker  # noqa: E402
from api.services.embedding_service import EmbeddingService  # noqa: E402
from api.services.ollama_service import OllamaService  # noqa: E402

# File extensions worth indexing. `.xql` is treated as plain text.
INDEX_EXTENSIONS = {".md", ".xql", ".json", ".txt"}

# Files we skip (too large, binary, or generated artefacts).
SKIP_NAMES = {"PROVENANCE.md", "packs_index.md"}

DATA_DIR = REPO_ROOT / "data" / "rag" / "chroma"
DEFAULT_COLLECTION = "xql_corpus"
DEFAULT_CORPUS = REPO_ROOT / "docs" / "seed" / "xql"


def file_metadata(path: Path, corpus_root: Path) -> dict:
    """Build per-chunk metadata derived from the file's location in the corpus tree.

    Robust to two ways of invoking ingest:
      (a) --corpus-dir docs/seed/xql        (rel paths start with packs/ or reference/)
      (b) --corpus-dir docs/seed/xql/packs  (rel paths start with <pack_name>/)

    In case (b) the parts[0] == "packs" guard would otherwise skip the
    pack_name / pack_role / category metadata. We detect this by checking
    whether the corpus_root itself is named "packs" or "reference".
    """
    rel = path.relative_to(corpus_root)
    parts = rel.parts
    root_name = corpus_root.name
    meta = {
        "source_path": str(rel),
        "filename": path.name,
        "ext": path.suffix.lower(),
    }

    # Normalised parts that ALWAYS start with packs/ or reference/ when the
    # file sits inside one of those subtrees, regardless of which dir was
    # passed as --corpus-dir.
    if root_name == "packs":
        norm_parts = ("packs", *parts)
    elif root_name == "reference":
        norm_parts = ("reference", *parts)
    else:
        norm_parts = parts

    if norm_parts[0] == "packs" and len(norm_parts) >= 2:
        meta["category"] = "pack"
        meta["pack_name"] = norm_parts[1]
        meta["pack_role"] = path.stem  # parser / datamodel / documentation
    elif norm_parts[0] == "reference":
        meta["category"] = "reference"
        meta["doc_name"] = path.stem
    elif path.name == "snippets.json":
        meta["category"] = "snippet_index"
    elif path.name == "few_shot_examples.json":
        meta["category"] = "few_shot_examples"
    elif path.name == "field_anchors.json":
        meta["category"] = "field_anchors"
    elif path.name == "xql-xdm-knowledge.md":
        meta["category"] = "core_knowledge"
    else:
        meta["category"] = "other"
    return meta


def collect_files(corpus_dir: Path) -> list[Path]:
    out = []
    for p in corpus_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in INDEX_EXTENSIONS:
            continue
        if p.name in SKIP_NAMES:
            continue
        out.append(p)
    return sorted(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest the XQL/XDM corpus into a dedicated ChromaDB collection.")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--collection", type=str, default=DEFAULT_COLLECTION)
    parser.add_argument("--reset", action="store_true", help="Drop the collection before ingesting")
    parser.add_argument("--dry-run", action="store_true", help="Walk and chunk but do not write to Chroma")
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("RAG_CHUNK_SIZE", "768")))
    parser.add_argument("--chunk-overlap", type=int, default=int(os.getenv("RAG_CHUNK_OVERLAP", "96")))
    args = parser.parse_args()

    corpus_dir = args.corpus_dir.resolve()
    if not corpus_dir.is_dir():
        print(f"[FAIL] corpus dir not found: {corpus_dir}")
        return 1

    files = collect_files(corpus_dir)
    print(f"[INFO] {len(files)} files queued from {corpus_dir.relative_to(REPO_ROOT)}")

    chunker = Chunker(chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)

    if args.dry_run:
        # Walk + chunk only, no embeddings or writes
        total = 0
        per_cat: dict[str, int] = {}
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            n = len(chunker.split(text))
            total += n
            cat = file_metadata(f, corpus_dir)["category"]
            per_cat[cat] = per_cat.get(cat, 0) + n
        print(f"[OK] dry-run: {total} chunks total")
        for cat, n in sorted(per_cat.items()):
            print(f"      {cat:>20s}: {n} chunks")
        return 0

    # Live ingest path — needs Ollama (or sentence-transformers) up.
    ollama = OllamaService()
    embed = EmbeddingService(ollama_service=ollama)
    print(f"[INFO] embedding backend: {embed.describe()}")

    import chromadb
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(DATA_DIR))

    if args.reset:
        try:
            client.delete_collection(name=args.collection)
            print(f"[OK] dropped existing collection '{args.collection}'")
        except Exception:
            pass

    try:
        coll = client.get_collection(name=args.collection)
        print(f"[INFO] using existing collection '{args.collection}' ({coll.count()} docs)")
    except Exception:
        coll = client.create_collection(name=args.collection, metadata=embed.describe())
        print(f"[OK] created collection '{args.collection}' with metadata {embed.describe()}")

    # Build the index. We use stable IDs keyed on path+chunk-index+content-hash
    # so re-ingest is idempotent.
    added = skipped = 0
    for fi, f in enumerate(files):
        text = f.read_text(encoding="utf-8", errors="ignore")
        chunks = chunker.split(text)
        if not chunks:
            continue
        meta_base = file_metadata(f, corpus_dir)
        ids: list[str] = []
        docs: list[str] = []
        metas: list[dict] = []
        for ci, chunk in enumerate(chunks):
            h = hashlib.sha256(chunk.encode("utf-8", errors="ignore")).hexdigest()[:12]
            cid = f"{meta_base['source_path']}::chunk{ci:04d}::{h}"
            ids.append(cid)
            docs.append(chunk)
            m = dict(meta_base)
            m["chunk_index"] = ci
            m["chunk_hash"] = h
            metas.append(m)

        # Cheap dedup: ask Chroma which IDs already exist
        try:
            existing = coll.get(ids=ids, include=[])
            existing_ids = set(existing.get("ids") or [])
        except Exception:
            existing_ids = set()
        keep_ix = [i for i, cid in enumerate(ids) if cid not in existing_ids]
        if not keep_ix:
            skipped += len(ids)
            print(f"  [{fi + 1:3d}/{len(files)}] [SKIP] {meta_base['source_path']} ({len(ids)} chunks already indexed)")
            continue

        keep_docs = [docs[i] for i in keep_ix]
        keep_ids = [ids[i] for i in keep_ix]
        keep_metas = [metas[i] for i in keep_ix]
        vectors = embed.embed(keep_docs)

        coll.add(
            ids=keep_ids,
            documents=keep_docs,
            embeddings=vectors,
            metadatas=keep_metas,
        )
        added += len(keep_ix)
        print(f"  [{fi + 1:3d}/{len(files)}] [OK]   {meta_base['source_path']} (+{len(keep_ix)} chunks)")

    print()
    print(f"[OK] ingest complete: {added} chunks added, {skipped} skipped")
    print(f"     collection '{args.collection}' now contains {coll.count()} chunks")
    # Emit a small manifest JSON for downstream tooling and Gate 2 review.
    manifest = {
        "collection": args.collection,
        "corpus_dir": str(corpus_dir.relative_to(REPO_ROOT)),
        "embedding_backend": embed.describe(),
        "chunk_size": args.chunk_size,
        "chunk_overlap": args.chunk_overlap,
        "file_count": len(files),
        "chunks_added": added,
        "chunks_skipped": skipped,
        "total_chunks": coll.count(),
    }
    manifest_path = DEFAULT_CORPUS / "ingest_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] wrote manifest: {manifest_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
