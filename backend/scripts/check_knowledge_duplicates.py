import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal


def main() -> int:
    with SessionLocal() as db:
        inspector = inspect(db.bind)
        can_check_documents = _has_columns(inspector, "knowledge_documents", {"source_type", "file_hash"})
        can_check_chunks = _has_columns(inspector, "knowledge_chunks", {"document_id", "chunk_index"})
        document_duplicates = _find_document_duplicates(db) if can_check_documents else []
        chunk_duplicates = _find_chunk_duplicates(db) if can_check_chunks else []

    if not document_duplicates and not chunk_duplicates:
        if can_check_documents and can_check_chunks:
            print("OK: no duplicate knowledge_documents(source_type, file_hash) or knowledge_chunks(document_id, chunk_index) rows found.")
        else:
            print("OK: duplicate checks that could run found no duplicates. Skipped checks are listed above.")
        return 0

    print("Duplicate knowledge base rows found. Do not run alembic upgrade head until these are reviewed.")
    if document_duplicates:
        print("\nDuplicate knowledge_documents by source_type + file_hash:")
        for group in document_duplicates:
            print(f"- source_type={group['source_type']} file_hash={group['file_hash']} count={group['count']}")
            for item in group["items"]:
                print(
                    "  "
                    f"document_id={item['id']} "
                    f"file_name={item['file_name']} "
                    f"parse_status={item['parse_status']} "
                    f"updated_at={item['updated_at']}"
                )

    if chunk_duplicates:
        print("\nDuplicate knowledge_chunks by document_id + chunk_index:")
        for group in chunk_duplicates:
            print(f"- document_id={group['document_id']} chunk_index={group['chunk_index']} count={group['count']}")
            for item in group["items"]:
                print(
                    "  "
                    f"chunk_id={item['chunk_id']} "
                    f"document_id={item['document_id']} "
                    f"file_name={item['file_name']} "
                    f"parse_status={item['parse_status']} "
                    f"updated_at={item['updated_at']}"
                )

    print(
        "\nNext step: review each duplicate group manually, decide which document/chunk rows to keep, "
        "back up the database, remove or merge only the confirmed duplicates, then rerun this script."
    )
    return 1


def _find_document_duplicates(db) -> list[dict]:
    groups = db.execute(text(
        """
        SELECT source_type, file_hash, COUNT(*) AS count
        FROM knowledge_documents
        WHERE source_type = 'file' AND file_hash IS NOT NULL
        GROUP BY source_type, file_hash
        HAVING COUNT(*) > 1
        ORDER BY count DESC, file_hash
        """
    )).mappings().all()

    result: list[dict] = []
    for group in groups:
        items = db.execute(text(
            """
            SELECT id, file_name, parse_status, updated_at
            FROM knowledge_documents
            WHERE source_type = :source_type AND file_hash = :file_hash
            ORDER BY updated_at DESC, created_at DESC, id
            """
        ), {"source_type": group["source_type"], "file_hash": group["file_hash"]}).mappings().all()
        result.append({
            "source_type": group["source_type"],
            "file_hash": group["file_hash"],
            "count": group["count"],
            "items": [dict(item) for item in items],
        })
    return result


def _find_chunk_duplicates(db) -> list[dict]:
    groups = db.execute(text(
        """
        SELECT document_id, chunk_index, COUNT(*) AS count
        FROM knowledge_chunks
        WHERE document_id IS NOT NULL
        GROUP BY document_id, chunk_index
        HAVING COUNT(*) > 1
        ORDER BY count DESC, document_id, chunk_index
        """
    )).mappings().all()

    result: list[dict] = []
    for group in groups:
        items = db.execute(text(
            """
            SELECT
                c.id AS chunk_id,
                c.document_id,
                d.file_name,
                d.parse_status,
                c.updated_at
            FROM knowledge_chunks c
            LEFT JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.document_id = :document_id AND c.chunk_index = :chunk_index
            ORDER BY c.updated_at DESC, c.created_at DESC, c.id
            """
        ), {"document_id": group["document_id"], "chunk_index": group["chunk_index"]}).mappings().all()
        result.append({
            "document_id": group["document_id"],
            "chunk_index": group["chunk_index"],
            "count": group["count"],
            "items": [dict(item) for item in items],
        })
    return result


def _has_columns(inspector, table_name: str, required_columns: set[str]) -> bool:
    if not inspector.has_table(table_name):
        print(f"SKIP: {table_name} table does not exist.")
        return False
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing = sorted(required_columns - existing_columns)
    if missing:
        print(f"SKIP: {table_name} missing columns: {', '.join(missing)}.")
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
