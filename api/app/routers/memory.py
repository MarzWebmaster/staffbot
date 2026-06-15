"""
Customer Memory API Router v2
Endpoints: add, upload file, extract link, search, recent (paginated), stats, delete
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.middleware.auth import get_current_client
from app.models.client import Client

logger = logging.getLogger(__name__)
router = APIRouter()


# ── REQUEST/RESPONSE MODELS ─────────────────────────────────

class MemoryAddRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    title: Optional[str] = Field(None, max_length=500)
    memory_type: str = Field(default="conversation", pattern="^(conversation|knowledge|preference|fact)$")
    importance: int = Field(default=5, ge=0, le=10)
    source: str = Field(default="manual", max_length=100)


class MemoryUpdateRequest(BaseModel):
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    title: Optional[str] = Field(None, max_length=500)
    importance: Optional[int] = Field(None, ge=0, le=10)
    memory_type: Optional[str] = None


class LinkExtractRequest(BaseModel):
    url: str = Field(..., min_length=10, max_length=2000)
    title: Optional[str] = Field(None, max_length=500)
    memory_type: Optional[str] = None
    importance: int = Field(default=5, ge=0, le=10)


# ── ENDPOINTS ───────────────────────────────────────────────

@router.post("/add")
async def add_memory(
    data: MemoryAddRequest,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Add a memory item for the current customer."""
    from app.services.memory_service import TenantMemoryGuard
    from app.services.memory_processor import classify_memory_type, generate_title

    guard = TenantMemoryGuard(current_user.id, db)

    # Auto-generate title if not provided
    title = data.title
    if not title:
        title = await generate_title(data.content)

    # Auto-classify if not provided or default
    memory_type = data.memory_type
    if memory_type == "conversation":
        classified = await classify_memory_type(data.content)
        if classified != "conversation":
            memory_type = classified

    result = await guard.add(
        content=data.content,
        memory_type=memory_type,
        importance=data.importance,
        source=data.source,
    )

    # Update with title
    if title and result.get("id"):
        await db.execute(
            text("UPDATE client_memory SET title = :title WHERE id = :id"),
            {"title": title, "id": result["id"]}
        )
        await db.commit()
        result["title"] = title

    return {"success": True, "memory": result}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    memory_type: Optional[str] = Form(None),
    importance: int = Form(5),
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file (PDF, DOCX, TXT, HTML, CSV, JSON, images). Max 20MB."""
    from app.services.memory_service import TenantMemoryGuard
    from app.services.memory_processor import process_file_upload

    # Read file content
    raw_bytes = await file.read()
    file_name = file.filename or "uploaded_file"
    file_type = file.content_type or "application/octet-stream"

    try:
        doc = await process_file_upload(
            raw_bytes=raw_bytes,
            file_name=file_name,
            file_type=file_type,
            title=title,
            memory_type=memory_type,
            importance=importance,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"File processing error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

    guard = TenantMemoryGuard(current_user.id, db)

    # Store chunks
    stored_chunks = []
    parent_id = None

    for chunk in doc.chunks:
        result = await guard.add(
            content=chunk.content,
            memory_type=doc.memory_type,
            importance=importance,
            source="file_upload",
            metadata={
                **(doc.metadata or {}),
                "file_name": doc.file_name,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "chunk_index": chunk.index,
                "total_chunks": chunk.total,
                "source_page": chunk.source_page,
                "parent_id": parent_id,
            },
        )

        # Set title and file fields
        if result.get("id"):
            await db.execute(
                text("""
                    UPDATE client_memory 
                    SET title = :title,
                        file_name = :file_name,
                        file_type = :file_type,
                        file_size = :file_size,
                        chunk_index = :chunk_index,
                        total_chunks = :total_chunks,
                        parent_id = :parent_id
                    WHERE id = :id
                """),
                {
                    "title": doc.title if chunk.index == 0 else f"{doc.title} (part {chunk.index + 1}/{chunk.total})",
                    "file_name": doc.file_name,
                    "file_type": doc.file_type,
                    "file_size": doc.file_size,
                    "chunk_index": chunk.index,
                    "total_chunks": chunk.total,
                    "parent_id": parent_id if chunk.index > 0 else result["id"],
                    "id": result["id"],
                }
            )

            if chunk.index == 0:
                parent_id = result["id"]

            stored_chunks.append(result)

    await db.commit()

    return {
        "success": True,
        "title": doc.title,
        "file_name": doc.file_name,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "memory_type": doc.memory_type,
        "total_chunks": len(doc.chunks),
        "stored_chunks": len(stored_chunks),
        "parent_id": parent_id,
    }


@router.post("/extract-link")
async def extract_link(
    data: LinkExtractRequest,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Extract content from a URL and store as memory."""
    from app.services.memory_service import TenantMemoryGuard
    from app.services.memory_processor import process_link

    try:
        doc = await process_link(
            url=data.url,
            title=data.title,
            memory_type=data.memory_type,
            importance=data.importance,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Link extraction error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to extract link: {str(e)}")

    guard = TenantMemoryGuard(current_user.id, db)

    stored_chunks = []
    parent_id = None

    for chunk in doc.chunks:
        result = await guard.add(
            content=chunk.content,
            memory_type=doc.memory_type,
            importance=data.importance,
            source="link_extraction",
            metadata={
                **(doc.metadata or {}),
                "source_url": data.url,
                "chunk_index": chunk.index,
                "total_chunks": chunk.total,
            },
        )

        if result.get("id"):
            await db.execute(
                text("""
                    UPDATE client_memory 
                    SET title = :title,
                        source_url = :source_url,
                        chunk_index = :chunk_index,
                        total_chunks = :total_chunks,
                        parent_id = :parent_id
                    WHERE id = :id
                """),
                {
                    "title": doc.title if chunk.index == 0 else f"{doc.title} (part {chunk.index + 1}/{chunk.total})",
                    "source_url": data.url,
                    "chunk_index": chunk.index,
                    "total_chunks": chunk.total,
                    "parent_id": parent_id if chunk.index > 0 else result["id"],
                    "id": result["id"],
                }
            )

            if chunk.index == 0:
                parent_id = result["id"]

            stored_chunks.append(result)

    await db.commit()

    return {
        "success": True,
        "title": doc.title,
        "url": data.url,
        "memory_type": doc.memory_type,
        "total_chunks": len(doc.chunks),
        "stored_chunks": len(stored_chunks),
        "parent_id": parent_id,
    }


@router.get("/search")
async def search_memory(
    q: str = Query(..., min_length=1, max_length=500),
    memory_type: Optional[str] = Query(None),
    limit: int = Query(default=10, ge=1, le=50),
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Search customer memories."""
    from app.services.memory_service import TenantMemoryGuard

    guard = TenantMemoryGuard(current_user.id, db)
    results = await guard.search(
        query=q,
        memory_type=memory_type,
        limit=limit,
    )
    return {"success": True, "count": len(results), "memories": results}


@router.get("/recent")
async def recent_memory(
    memory_type: Optional[str] = Query(None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=5, ge=1, le=50),
    days: Optional[int] = Query(None, ge=1, le=365),
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get recent memories with pagination. Only shows parent items (not chunks)."""
    offset = (page - 1) * per_page

    # Build query — only show parent items (chunks are children)
    where_clauses = ["client_id = :client_id", "is_archived = false"]
    params = {"client_id": current_user.id, "limit": per_page, "offset": offset}

    if memory_type:
        where_clauses.append("memory_type = :memory_type")
        params["memory_type"] = memory_type

    if days:
        where_clauses.append("created_at > NOW() - INTERVAL ':days days'")
        params["days"] = days

    where_sql = " AND ".join(where_clauses)

    # Count total (parent items only: parent_id IS NULL OR id = parent_id)
    count_query = f"""
        SELECT COUNT(*) FROM client_memory 
        WHERE {where_sql} AND (parent_id IS NULL OR id = parent_id)
    """
    count_result = await db.execute(text(count_query), params)
    total = count_result.scalar()

    # Fetch page
    data_query = f"""
        SELECT id, title, content, memory_type, importance, source, 
               file_name, file_type, file_size, source_url,
               chunk_index, total_chunks, parent_id,
               metadata, created_at, updated_at
        FROM client_memory 
        WHERE {where_sql} AND (parent_id IS NULL OR id = parent_id)
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(data_query), params)
    rows = result.fetchall()

    memories = []
    for row in rows:
        # Truncate content for list view
        content_preview = row[2][:300] + "..." if row[2] and len(row[2]) > 300 else row[2]
        
        memories.append({
            "id": row[0],
            "title": row[1],
            "content": content_preview,
            "full_content": row[2],
            "memory_type": row[3],
            "importance": row[4],
            "source": row[5],
            "file_name": row[6],
            "file_type": row[7],
            "file_size": row[8],
            "source_url": row[9],
            "chunk_index": row[10],
            "total_chunks": row[11],
            "parent_id": row[12],
            "metadata": row[13],
            "created_at": row[14].isoformat() if row[14] else None,
            "updated_at": row[15].isoformat() if row[15] else None,
        })

    total_pages = max(1, (total + per_page - 1) // per_page)

    return {
        "success": True,
        "memories": memories,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    }


@router.get("/stats")
async def memory_stats(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get memory stats for the current customer."""
    from app.services.memory_service import TenantMemoryGuard

    guard = TenantMemoryGuard(current_user.id, db)
    stats = await guard.get_stats()

    # Get package limits
    result = await db.execute(
        text("""
            SELECT p.memory_item_limit, p.knowledge_item_limit, p.memory_retention_days
            FROM packages p
            JOIN clients c ON c.package = p.name
            WHERE c.id = :client_id
        """),
        {"client_id": current_user.id}
    )
    limits = result.first()

    # Count by type
    type_counts = await db.execute(
        text("""
            SELECT memory_type, COUNT(*) FROM client_memory 
            WHERE client_id = :cid AND is_archived = false AND (parent_id IS NULL OR id = parent_id)
            GROUP BY memory_type
        """),
        {"cid": current_user.id}
    )

    by_type = {row[0]: row[1] for row in type_counts.fetchall()}

    # Count documents (items with files or links)
    doc_count = await db.execute(
        text("""
            SELECT COUNT(*) FROM client_memory 
            WHERE client_id = :cid AND is_archived = false 
            AND (file_name IS NOT NULL OR source_url IS NOT NULL)
            AND (parent_id IS NULL OR id = parent_id)
        """),
        {"cid": current_user.id}
    )

    return {
        "success": True,
        "stats": {
            **stats,
            "by_type": by_type,
            "documents": doc_count.scalar() or 0,
        },
        "limits": {
            "memory_item_limit": limits[0] if limits else None,
            "knowledge_item_limit": limits[1] if limits else None,
            "memory_retention_days": limits[2] if limits else None,
        },
    }



@router.get("/audit-log")
async def memory_audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get memory audit log for the current customer."""
    result = await db.execute(
        text("""
            SELECT id, action, memory_type, item_count, reason, performed_by, created_at
            FROM memory_audit_log
            WHERE client_id = :client_id
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"client_id": current_user.id, "limit": limit}
    )

    logs = [
        {
            "id": row[0],
            "action": row[1],
            "memory_type": row[2],
            "item_count": row[3],
            "reason": row[4],
            "performed_by": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
        }
        for row in result.fetchall()
    ]

    return {"success": True, "logs": logs}



@router.get("/{memory_id}")
async def get_memory_detail(
    memory_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get full memory detail including chunks."""
    result = await db.execute(
        text("""
            SELECT id, title, content, memory_type, importance, source,
                   file_name, file_type, file_size, source_url,
                   chunk_index, total_chunks, parent_id, metadata, created_at
            FROM client_memory 
            WHERE id = :id AND client_id = :client_id AND is_archived = false
        """),
        {"id": memory_id, "client_id": current_user.id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")

    # If this is a parent, get all chunks
    chunks = []
    if row[12] is None or row[12] == row[0]:  # parent_id is null or self
        chunk_result = await db.execute(
            text("""
                SELECT id, title, content, chunk_index, total_chunks, created_at
                FROM client_memory 
                WHERE (parent_id = :parent_id OR id = :parent_id) AND is_archived = false
                ORDER BY chunk_index
            """),
            {"parent_id": row[0]}
        )
        for cr in chunk_result.fetchall():
            chunks.append({
                "id": cr[0],
                "title": cr[1],
                "content": cr[2],
                "chunk_index": cr[3],
                "total_chunks": cr[4],
                "created_at": cr[5].isoformat() if cr[5] else None,
            })

    return {
        "success": True,
        "memory": {
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "memory_type": row[3],
            "importance": row[4],
            "source": row[5],
            "file_name": row[6],
            "file_type": row[7],
            "file_size": row[8],
            "source_url": row[9],
            "chunk_index": row[10],
            "total_chunks": row[11],
            "parent_id": row[12],
            "metadata": row[13],
            "created_at": row[14].isoformat() if row[14] else None,
        },
        "chunks": chunks,
    }


@router.put("/{memory_id}")
async def update_memory(
    memory_id: int,
    data: MemoryUpdateRequest,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Update a memory item."""
    # Verify ownership
    result = await db.execute(
        text("SELECT id FROM client_memory WHERE id = :id AND client_id = :cid"),
        {"id": memory_id, "cid": current_user.id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Memory not found")

    updates = []
    params = {"id": memory_id}
    if data.content is not None:
        updates.append("content = :content")
        params["content"] = data.content
    if data.title is not None:
        updates.append("title = :title")
        params["title"] = data.title
    if data.importance is not None:
        updates.append("importance = :importance")
        params["importance"] = data.importance
    if data.memory_type is not None:
        updates.append("memory_type = :memory_type")
        params["memory_type"] = data.memory_type

    if updates:
        updates.append("updated_at = NOW()")
        await db.execute(
            text(f"UPDATE client_memory SET {', '.join(updates)} WHERE id = :id"),
            params
        )
        await db.commit()

    return {"success": True, "message": "Memory updated"}



@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific memory item and its chunks."""
    from app.services.memory_service import TenantMemoryGuard

    guard = TenantMemoryGuard(current_user.id, db)

    # Delete chunks too
    await db.execute(
        text("DELETE FROM client_memory WHERE parent_id = :id AND client_id = :cid"),
        {"id": memory_id, "cid": current_user.id}
    )

    deleted = await guard.delete_one(memory_id, performed_by="customer")
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")

    return {"success": True, "message": "Memory deleted"}


@router.delete("/type/{memory_type}")
async def delete_by_type(
    memory_type: str,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Delete all memories of a specific type."""
    from app.services.memory_service import TenantMemoryGuard

    if memory_type not in ("conversation", "knowledge", "preference", "fact"):
        raise HTTPException(status_code=400, detail="Invalid memory type")

    guard = TenantMemoryGuard(current_user.id, db)
    count = await guard.delete_by_type(memory_type, performed_by="customer")

    return {"success": True, "deleted": count}


@router.delete("/clear/all")
async def clear_all_memory(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Nuclear option — delete ALL memories for the current customer."""
    from app.services.memory_service import TenantMemoryGuard

    guard = TenantMemoryGuard(current_user.id, db)
    count = await guard.delete_all(performed_by="customer")

    return {"success": True, "deleted": count, "message": f"Deleted {count} memories"}



@router.post("/backfill-embeddings")
async def backfill_embeddings(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Backfill embeddings for memories that don't have them."""
    from app.services.memory_service import TenantMemoryGuard

    guard = TenantMemoryGuard(current_user.id, db)

    result = await db.execute(
        text("SELECT id, content FROM client_memory WHERE client_id = :cid AND embedding IS NULL AND is_archived = false"),
        {"cid": current_user.id}
    )
    rows = result.all()

    if not rows:
        return {"success": True, "message": "All memories have embeddings", "backfilled": 0}

    backfilled = 0
    errors = 0
    for row in rows:
        try:
            embedding = await guard._get_embedding(row[1])
            if embedding:
                vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
                await db.execute(
                    text("UPDATE client_memory SET embedding = CAST(:vec AS vector) WHERE id = :id"),
                    {"vec": vec_str, "id": row[0]}
                )
                backfilled += 1
        except Exception as e:
            errors += 1

    await db.commit()
    return {"success": True, "backfilled": backfilled, "errors": errors, "total_without": len(rows)}


# ── ADMIN: RETENTION CLEANUP CRON ──────────────────────────

from app.middleware.auth import get_current_admin

@router.post("/admin/retention-cleanup")
async def admin_retention_cleanup(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Run nightly retention cleanup for all customers. Admin only."""
    from app.services.memory_service import run_retention_cleanup
    result = await run_retention_cleanup(db)
    return {"success": True, "result": result}


@router.post("/admin/delete-customer/{client_id}")
async def admin_delete_customer_memories(
    client_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete ALL memories for a customer. Admin only."""
    from app.services.memory_service import delete_customer_memories
    count = await delete_customer_memories(client_id, db, performed_by="admin")
    return {"success": True, "deleted": count}
