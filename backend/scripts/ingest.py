"""
Ingestion pipeline — load, chunk, embed, and store Lenny's Podcast transcripts.

This is the main entry point for populating the knowledge base.
Run it with: python -m scripts.ingest

PIPELINE:
  1. Clone/update the transcripts repo from GitHub
  2. Discover all transcript.md files
  3. Parse each transcript (YAML frontmatter + content)
  4. Chunk each transcript into ~512 character segments
  5. Generate embeddings for all chunks (batched)
  6. Store chunks + embeddings in PostgreSQL/pgvector
  7. Report ingestion stats

DECISION: Idempotent ingestion
  Running the script twice doesn't create duplicate chunks. We use
  UPSERT (INSERT ... ON CONFLICT DO UPDATE) keyed on
  (transcript_name, chunk_index). This means:
  - First run: inserts all chunks
  - Second run: updates existing chunks (useful if we change chunking)
  - New transcripts added to the repo: only new chunks are inserted

DECISION: Synchronous script over async
  The ingestion runs once (or rarely). Using async here adds complexity
  for zero benefit — we're not handling concurrent requests. We use
  psycopg2 (sync) directly instead of asyncpg.

DECISION: Clone the repo vs. downloading a release
  The repo is a git repository with 269 Markdown files. `git clone` is
  the simplest way to get all files. We shallow-clone (--depth 1) to
  avoid downloading the full commit history (~10MB savings).
"""

import os
import sys
import time
import subprocess
from pathlib import Path

# Add the backend directory to the Python path so we can import app modules
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.services.chunking import chunk_transcript, extract_speaker_from_chunk, extract_timestamp_from_chunk
from app.services.transcript_parser import parse_transcript_file, discover_transcripts
from app.services.embedding import get_embedding_service


# --- Configuration ---
TRANSCRIPTS_REPO = "https://github.com/ChatPRD/lennys-podcast-transcripts.git"
DATA_DIR = Path(BACKEND_DIR).parent / "data" / "transcripts"
EPISODES_DIR = DATA_DIR / "episodes"
BATCH_SIZE = 64  # Embedding batch size


def get_sync_db_url() -> str:
    """Build a sync psycopg2 connection string from settings."""
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname={settings.postgres_db} user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )


def step_1_clone_repo():
    """
    Clone or update the transcripts repository.

    DECISION: git clone --depth 1 (shallow clone)
      We only need the latest files, not the commit history.
      Saves ~50% download time and disk space.

    If the directory already exists, we do a git pull instead.
    """
    print("\n📥 Step 1: Cloning/updating transcripts repository...")

    if DATA_DIR.exists() and (DATA_DIR / ".git").exists():
        print(f"   Repository already exists at {DATA_DIR}, pulling latest...")
        result = subprocess.run(
            ["git", "pull"],
            cwd=str(DATA_DIR),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"   ⚠️  Git pull failed: {result.stderr}")
            print("   Continuing with existing files...")
        else:
            print(f"   ✅ Updated: {result.stdout.strip()}")
    else:
        print(f"   Cloning {TRANSCRIPTS_REPO}...")
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            ["git", "clone", "--depth", "1", TRANSCRIPTS_REPO, str(DATA_DIR)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"   ❌ Clone failed: {result.stderr}")
            sys.exit(1)
        print(f"   ✅ Cloned to {DATA_DIR}")


def step_2_discover_and_parse(episodes_dir: Path) -> list:
    """
    Discover all transcript files and parse them.

    Returns:
        List of (parsed_transcript, chunks) tuples.
    """
    print("\n📄 Step 2: Discovering and parsing transcripts...")

    transcript_paths = discover_transcripts(episodes_dir)
    print(f"   Found {len(transcript_paths)} transcript files")

    all_data = []
    parse_errors = 0

    for path in transcript_paths:
        parsed = parse_transcript_file(path)
        if parsed is None:
            parse_errors += 1
            continue

        chunks = chunk_transcript(
            parsed.content,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        if not chunks:
            parse_errors += 1
            continue

        # Enrich chunk metadata
        for chunk in chunks:
            chunk.speaker = extract_speaker_from_chunk(chunk.content)
            chunk.timestamp = extract_timestamp_from_chunk(chunk.content)

        all_data.append((parsed, chunks))

    total_chunks = sum(len(chunks) for _, chunks in all_data)
    print(f"   ✅ Parsed {len(all_data)} transcripts into {total_chunks} chunks")
    if parse_errors:
        print(f"   ⚠️  {parse_errors} transcripts had parse errors (skipped)")

    return all_data


def step_3_generate_embeddings(all_data: list) -> list:
    """
    Generate embeddings for all chunks in batches.

    DECISION: Embed all chunks in memory before DB insertion
      Alternative: embed and insert one transcript at a time.
      Batch embedding is ~10x faster because sentence-transformers
      uses vectorized operations. The memory cost is ~50MB for 10k
      384-dim vectors — well within limits.

    Returns:
        The all_data list, with embeddings added to each chunk.
    """
    print("\n🧠 Step 3: Generating embeddings...")

    embedding_service = get_embedding_service()

    # Collect all chunk texts for batch embedding
    all_texts = []
    chunk_map = []  # Maps flat index back to (transcript_idx, chunk_idx)

    for t_idx, (parsed, chunks) in enumerate(all_data):
        for c_idx, chunk in enumerate(chunks):
            all_texts.append(chunk.content)
            chunk_map.append((t_idx, c_idx))

    print(f"   Embedding {len(all_texts)} chunks (batch_size={BATCH_SIZE})...")
    start = time.time()

    all_embeddings = embedding_service.embed_batch(all_texts, batch_size=BATCH_SIZE)

    elapsed = time.time() - start
    print(f"   ✅ Embeddings generated in {elapsed:.1f}s ({len(all_texts)/elapsed:.0f} chunks/sec)")

    # Attach embeddings back to chunks
    for flat_idx, (t_idx, c_idx) in enumerate(chunk_map):
        all_data[t_idx][1][c_idx].embedding = all_embeddings[flat_idx]

    return all_data


def step_4_store_in_db(all_data: list):
    """
    Store all chunks and embeddings in PostgreSQL.

    DECISION: Batch UPSERT with executemany
      - UPSERT (ON CONFLICT DO UPDATE) makes ingestion idempotent
      - executemany with psycopg2.extras.execute_values is ~5x faster
        than individual INSERT statements
      - We commit in batches of 100 transcripts to avoid holding a
        single massive transaction
    """
    print("\n💾 Step 4: Storing in PostgreSQL...")

    conn = psycopg.connect(get_sync_db_url())
    cursor = conn.cursor()

    total_inserted = 0
    total_updated = 0

    upsert_sql = """
        INSERT INTO transcript_chunks
            (transcript_name, chunk_index, content, embedding, metadata)
        VALUES (%s, %s, %s, %s::vector, %s)
        ON CONFLICT (transcript_name, chunk_index)
        DO UPDATE SET
            content = EXCLUDED.content,
            embedding = EXCLUDED.embedding,
            metadata = EXCLUDED.metadata
    """

    try:
        for batch_start in range(0, len(all_data), 100):
            batch = all_data[batch_start:batch_start + 100]

            values = []
            for parsed, chunks in batch:
                for chunk in chunks:
                    metadata = parsed.metadata.to_dict()
                    metadata["speaker"] = getattr(chunk, "speaker", None)
                    metadata["timestamp"] = getattr(chunk, "timestamp", None)

                    # pgvector expects embedding as a string: '[0.1, 0.2, ...]'
                    embedding_str = (
                        "[" + ",".join(str(x) for x in chunk.embedding) + "]"
                        if hasattr(chunk, "embedding") and chunk.embedding
                        else None
                    )

                    values.append((
                        parsed.file_name,      # transcript_name
                        chunk.chunk_index,     # chunk_index
                        chunk.content,         # content
                        embedding_str,         # embedding
                        Jsonb(metadata),  # metadata
                    ))

            if values:
                cursor.executemany(upsert_sql, values)
                conn.commit()
                total_inserted += len(values)

            print(f"   Progress: {min(batch_start + 100, len(all_data))}/{len(all_data)} transcripts")

    except Exception as e:
        conn.rollback()
        print(f"   ❌ Database error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

    print(f"   ✅ Stored {total_inserted} chunks in database")


def step_5_verify(all_data: list):
    """
    Verify the ingestion by running a test query.

    This is a sanity check — does retrieval actually work after ingestion?
    """
    print("\n🔍 Step 5: Verifying ingestion...")

    conn = psycopg.connect(get_sync_db_url())
    cursor = conn.cursor()

    # Count total chunks
    cursor.execute("SELECT COUNT(*) FROM transcript_chunks")
    total = cursor.fetchone()[0]
    print(f"   Total chunks in database: {total}")

    # Count unique transcripts
    cursor.execute("SELECT COUNT(DISTINCT transcript_name) FROM transcript_chunks")
    unique = cursor.fetchone()[0]
    print(f"   Unique transcripts: {unique}")

    # Test a similarity query
    print("   Running test query: 'product market fit'...")
    embedding_service = get_embedding_service()
    test_embedding = embedding_service.embed_text("product market fit")
    embedding_str = "[" + ",".join(str(x) for x in test_embedding) + "]"

    cursor.execute("""
        SELECT transcript_name, chunk_index,
               1 - (embedding <=> %s::vector) as similarity,
               LEFT(content, 100) as preview
        FROM transcript_chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT 3
    """, (embedding_str, embedding_str))

    results = cursor.fetchall()
    if results:
        print("   ✅ Test query results:")
        for name, idx, sim, preview in results:
            print(f"      [{sim:.4f}] {name} (chunk {idx}): {preview}...")
    else:
        print("   ⚠️  No results returned — check embeddings")

    cursor.close()
    conn.close()


def main():
    """Run the full ingestion pipeline."""
    print("=" * 60)
    print("🚀 Lenny Growth Assistant — Transcript Ingestion Pipeline")
    print("=" * 60)

    overall_start = time.time()

    # Step 1: Clone/update repo
    step_1_clone_repo()

    # Check if episodes directory exists
    if not EPISODES_DIR.exists():
        print(f"\n❌ Episodes directory not found at {EPISODES_DIR}")
        print("   The repo structure may have changed. Check manually.")
        sys.exit(1)

    # Step 2: Parse transcripts
    all_data = step_2_discover_and_parse(EPISODES_DIR)
    if not all_data:
        print("\n❌ No transcripts found to ingest!")
        sys.exit(1)

    # Step 3: Generate embeddings
    all_data = step_3_generate_embeddings(all_data)

    # Step 4: Store in database
    step_4_store_in_db(all_data)

    # Step 5: Verify
    step_5_verify(all_data)

    elapsed = time.time() - overall_start
    print(f"\n{'=' * 60}")
    print(f"✅ Ingestion complete in {elapsed:.1f}s")
    total_chunks = sum(len(chunks) for _, chunks in all_data)
    print(f"   {len(all_data)} transcripts → {total_chunks} chunks → pgvector")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
