import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))
app_env = os.getenv("APP_ENV", "dev").strip().lower()
default_env_file = BACKEND_DIR / (".env" if app_env == "prod" else ".env.dev")
env_file = Path(os.getenv("CAIYAN_ENV_FILE") or default_env_file)
os.environ.setdefault("CAIYAN_ENV_FILE", str(env_file))
load_dotenv(env_file, override=False)
os.environ["DEBUG"] = "false"

from app.core.database import SessionLocal  # noqa: E402
from app.services import product_vector_index_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Index product database rows into knowledge_chunks and pgvector embeddings.")
    parser.add_argument("--index-only", action="store_true", help="Only create/update knowledge documents and chunks.")
    parser.add_argument("--embed-only", action="store_true", help="Only embed pending/failed chunks.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum chunks to embed in this run.")
    parser.add_argument("--model", default=None, help="Embedding model id from system settings.")
    args = parser.parse_args()

    with SessionLocal() as db:
        if not args.embed_only:
            indexed = product_vector_index_service.index_all_products(db)
            print(f"Indexed products={indexed['products']} documents={indexed['documents']} chunks={indexed['chunks']}")

        if not args.index_only:
            embedded = product_vector_index_service.run_embed_pending_chunks(db, limit=args.limit, model=args.model)
            print(f"Embedded total={embedded['total']} synced={embedded['embedded']} failed={embedded['failed']}")
            if embedded["embedded"]:
                created = product_vector_index_service.create_embedding_index(db)
                if created:
                    print("Vector index ensured: idx_knowledge_chunks_embedding")
                else:
                    print("Vector index skipped: current embedding dimension is above pgvector ivfflat limit")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
