"""
Kometizarr Web UI - FastAPI Backend
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import sys
import threading
from datetime import datetime

# Add kometizarr to path
sys.path.insert(0, '/app/kometizarr')

from src.rating_overlay.plex_poster_manager import PlexPosterManager
from src.collection_manager.manager import CollectionManager
from src.utils.logger import setup_logger

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Kometizarr API", version="1.3.0")

# ── Run History Log ──────────────────────────────────────────────────────────
HISTORY_PATH = Path('/app/kometizarr/data/run_history.json')
MAX_HISTORY_ENTRIES = 100

def _load_history() -> list:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text())
    except Exception:
        return []

def _save_history(entries: list):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(entries[-MAX_HISTORY_ENTRIES:], indent=2))

def _record_run(run_type: str, library: str, total: int, success: int, failed: int, skipped: int, duration_seconds: float, force: bool = False):
    entries = _load_history()
    entries.append({
        'timestamp': datetime.now().isoformat(),
        'type': run_type,
        'library': library,
        'total': total,
        'success': success,
        'failed': failed,
        'skipped': skipped,
        'duration_seconds': round(duration_seconds, 1),
        'force': force,
    })
    _save_history(entries)

# ── API Rate Limiting (semaphore per provider) ───────────────────────────────
# Limits concurrent in-flight requests to each API provider
_rate_limiters = {
    'tmdb': threading.Semaphore(8),
    'omdb': threading.Semaphore(4),
    'mdblist': threading.Semaphore(4),
}

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket connections for live progress
active_connections: List[WebSocket] = []

# Processing state (sent over WebSocket - must be JSON serializable)
processing_state = {
    "is_processing": False,
    "current_library": None,
    "progress": 0,
    "total": 0,
    "success": 0,
    "failed": 0,
    "skipped": 0,
    "current_item": None,
    "stop_requested": False,
    "force_mode": False,
}

# Processing start time (stored separately - not sent over WebSocket)
processing_start_time = None

# Webhook item queue — serializes single-item processing requests
webhook_queue: asyncio.Queue = asyncio.Queue()

# Restore state (sent over WebSocket - must be JSON serializable)
restore_state = {
    "is_restoring": False,
    "current_library": None,
    "progress": 0,
    "total": 0,
    "restored": 0,
    "failed": 0,
    "skipped": 0,
    "current_item": None,
    "stop_requested": False,
}

# Restore start time (stored separately - not sent over WebSocket)
restore_start_time = None


class ProcessRequest(BaseModel):
    library_name: str
    position: str = "northwest"  # Legacy unified badge mode
    badge_position: Optional[Dict[str, float]] = None  # Legacy: free positioning for unified badge {x: %, y: %}
    badge_positions: Optional[Dict[str, Dict[str, float]]] = None  # New: individual badge positions {'tmdb': {'x': 5, 'y': 5}, ...}
    force: bool = False
    limit: Optional[int] = None
    rating_sources: Optional[Dict[str, bool]] = None  # Which ratings to show
    badge_style: Optional[Dict[str, Any]] = None  # Badge styling options
    rating_key: Optional[str] = None  # If set, process only this specific Plex item
    workers: int = 1  # Number of concurrent workers (1-10)


class ProcessBatchRequest(BaseModel):
    library_names: List[str]
    position: str = "northwest"
    badge_positions: Optional[Dict[str, Dict[str, float]]] = None
    force: bool = False
    rating_sources: Optional[Dict[str, bool]] = None
    badge_style: Optional[Dict[str, Any]] = None
    workers: int = 1
    # Per media-type settings (movie / tv)
    per_type_positions: Optional[Dict[str, Any]] = None
    per_type_style: Optional[Dict[str, Any]] = None
    per_type_sources: Optional[Dict[str, Any]] = None


class LibraryStats(BaseModel):
    library_name: str
    total_items: int
    processed_items: int
    success_rate: float


@app.get("/")
async def root():
    """Health check"""
    return {"status": "ok", "app": "Kometizarr API", "version": "1.2.1"}


@app.get("/api/libraries")
async def get_libraries():
    """Get all Plex libraries - optimized for speed"""
    try:
        from plexapi.server import PlexServer

        plex_url = os.getenv('PLEX_URL', 'http://192.168.1.20:32400')
        plex_token = os.getenv('PLEX_TOKEN')

        if not plex_token:
            return {"error": "PLEX_TOKEN not configured"}

        server = PlexServer(plex_url, plex_token)
        libraries = []

        for lib in server.library.sections():
            libraries.append({
                "name": lib.title,
                "type": lib.type,
                # Use totalSize instead of len(all()) - avoids fetching all items
                "count": lib.totalSize if hasattr(lib, 'totalSize') else 0
            })

        return {"libraries": libraries}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/library/{library_name}/stats")
async def get_library_stats(library_name: str):
    """Get statistics for a library"""
    try:
        from plexapi.server import PlexServer

        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')

        server = PlexServer(plex_url, plex_token)
        library = server.library.section(library_name)

        # Use totalSize for fast count instead of fetching all items
        total = library.totalSize

        # Check how many have backups (processed) - use fast glob count
        backup_dir = f"/backups/{library_name}"
        processed = 0
        if os.path.exists(backup_dir):
            import glob
            processed = len(glob.glob(f"{backup_dir}/*"))

        success_rate = (processed / total * 100) if total > 0 else 0

        return {
            "library_name": library_name,
            "total_items": total,
            "processed_items": processed,
            "success_rate": round(success_rate, 1)
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/process")
async def start_processing(request: ProcessRequest):
    """Start overlay processing"""
    global processing_state

    if processing_state["is_processing"]:
        return {"error": "Processing already in progress"}

    # Start background task
    asyncio.create_task(process_library_background(request))

    return {"status": "started", "library": request.library_name}


def _get_library_type(library_name: str) -> str:
    """Get the Plex library type ('movie' or 'show') for a library name."""
    try:
        from plexapi.server import PlexServer
        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')
        server = PlexServer(plex_url, plex_token)
        library = server.library.section(library_name)
        return library.type
    except Exception:
        return 'movie'


@app.post("/api/process-batch")
async def start_processing_batch(request: ProcessBatchRequest):
    """Process multiple libraries sequentially."""
    if processing_state["is_processing"]:
        return {"error": "Processing already in progress"}
    if not request.library_names:
        return {"error": "No libraries specified"}

    async def run_batch():
        for lib_name in request.library_names:
            # Resolve per-type settings if available
            lib_type = _get_library_type(lib_name)
            type_key = 'tv' if lib_type == 'show' else 'movie'

            bp = request.badge_positions
            bs = request.badge_style
            rs = request.rating_sources

            if request.per_type_positions and type_key in request.per_type_positions:
                bp = request.per_type_positions[type_key]
            if request.per_type_style and type_key in request.per_type_style:
                bs = request.per_type_style[type_key]
            if request.per_type_sources and type_key in request.per_type_sources:
                rs = request.per_type_sources[type_key]

            # Filter badge_positions to only enabled sources
            enabled_bp = None
            if bp and rs:
                enabled_bp = {k: v for k, v in bp.items() if rs.get(k, True)}
            else:
                enabled_bp = bp

            single = ProcessRequest(
                library_name=lib_name,
                position=request.position,
                badge_positions=enabled_bp,
                force=request.force,
                rating_sources=rs,
                badge_style=bs,
                workers=request.workers,
            )
            await process_library_background(single)

    asyncio.create_task(run_batch())
    return {"status": "started", "libraries": request.library_names}


@app.post("/api/restore")
async def restore_originals(request: ProcessRequest):
    """Start restoring original posters from backups"""
    global restore_state

    if restore_state["is_restoring"]:
        return {"error": "Restore already in progress"}

    # Start background task
    asyncio.create_task(restore_library_background(request))

    return {"status": "started", "library": request.library_name}


@app.post("/api/stop")
async def stop_processing():
    """Request graceful stop of current processing operation"""
    global processing_state

    if processing_state["is_processing"]:
        processing_state["stop_requested"] = True
        return {"status": "stopping", "message": "Processing will stop after current item"}

    return {"status": "idle", "message": "No processing in progress"}


@app.post("/api/restore/stop")
async def stop_restore():
    """Request graceful stop of current restore operation"""
    global restore_state

    if restore_state["is_restoring"]:
        restore_state["stop_requested"] = True
        return {"status": "stopping", "message": "Restore will stop after current item"}

    return {"status": "idle", "message": "No restore in progress"}


async def restore_library_background(request: ProcessRequest):
    """Background task for restoring library"""
    global restore_state, restore_start_time

    try:
        # Reset restore state for new run
        restore_state["is_restoring"] = True
        restore_state["current_library"] = request.library_name
        restore_state["progress"] = 0
        restore_state["total"] = 0
        restore_state["restored"] = 0
        restore_state["failed"] = 0
        restore_state["skipped"] = 0
        restore_state["current_item"] = None
        restore_start_time = datetime.now()

        from plexapi.server import PlexServer
        from src.rating_overlay.backup_manager import PosterBackupManager

        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')

        server = PlexServer(plex_url, plex_token)
        library = server.library.section(request.library_name)

        backup_manager = PosterBackupManager(backup_dir='/backups')

        # Get all items
        all_items = library.all()
        if request.limit:
            all_items = all_items[:request.limit]

        restore_state["total"] = len(all_items)

        logger.info(f"🔄 Restore started: {request.library_name} ({len(all_items)} items)")

        # Restore each item
        for i, item in enumerate(all_items, 1):
            # Check if stop was requested
            if restore_state["stop_requested"]:
                logger.info(f"Stop requested - stopping restore at item {i}/{restore_state['total']}")
                break

            restore_state["progress"] = i
            restore_state["current_item"] = item.title

            # Skip if no backup exists
            if not backup_manager.has_backup(request.library_name, item.title):
                restore_state["skipped"] += 1
            # Skip if already showing original (no overlay applied)
            elif not backup_manager.has_overlay(request.library_name, item.title):
                restore_state["skipped"] += 1
            # Has backup AND has overlay, proceed with restore
            else:
                if backup_manager.restore_original(request.library_name, item.title, item):
                    restore_state["restored"] += 1
                else:
                    restore_state["failed"] += 1

            # Broadcast progress to all WebSocket connections
            await broadcast_restore_progress()

            # Rate limiting
            await asyncio.sleep(0.1)

        restore_state["is_restoring"] = False
        restore_state["stop_requested"] = False

        # Calculate duration and stats
        duration = datetime.now() - restore_start_time
        duration_seconds = duration.total_seconds()
        duration_str = f"{int(duration_seconds // 3600)}h {int((duration_seconds % 3600) // 60)}m {int(duration_seconds % 60)}s" if duration_seconds >= 3600 else f"{int(duration_seconds // 60)}m {int(duration_seconds % 60)}s"

        total = restore_state["total"]
        restored = restore_state["restored"]
        failed = restore_state["failed"]
        skipped = restore_state["skipped"]

        restored_rate = (restored / total * 100) if total > 0 else 0
        failed_rate = (failed / total * 100) if total > 0 else 0
        skipped_rate = (skipped / total * 100) if total > 0 else 0
        rate_per_min = (total / (duration_seconds / 60)) if duration_seconds > 0 else 0

        # Log fancy summary
        logger.info("=" * 60)
        logger.info(f"✅ Restore Completed: {request.library_name}")
        logger.info("-" * 60)
        logger.info(f"Total Items:     {total}")
        logger.info(f"Restored:        {restored} ({restored_rate:.1f}%)")
        logger.info(f"Failed:          {failed} ({failed_rate:.1f}%)")
        logger.info(f"Skipped:         {skipped} ({skipped_rate:.1f}%)")
        logger.info(f"Duration:        {duration_str}")
        logger.info(f"Rate:            {rate_per_min:.1f} items/min")
        logger.info("=" * 60)

        # Record to run history
        _record_run('restore', request.library_name, total, restored, failed, skipped, duration_seconds)

        await broadcast_restore_progress()  # Final update

    except Exception as e:
        restore_state["is_restoring"] = False
        restore_state["stop_requested"] = False
        restore_state["error"] = str(e)
        logger.error(f"❌ Restore failed: {request.library_name} - Error: {e}")
        await broadcast_restore_progress()


async def process_library_background(request: ProcessRequest):
    """Background task for processing library"""
    global processing_state, processing_start_time

    try:
        # Reset processing state for new run
        processing_state["is_processing"] = True
        processing_state["current_library"] = request.library_name
        processing_state["progress"] = 0
        processing_state["total"] = 0
        processing_state["success"] = 0
        processing_state["failed"] = 0
        processing_state["skipped"] = 0
        processing_state["current_item"] = None
        processing_state["force_mode"] = request.force
        processing_start_time = datetime.now()

        # Initialize manager
        manager = PlexPosterManager(
            plex_url=os.getenv('PLEX_URL'),
            plex_token=os.getenv('PLEX_TOKEN'),
            library_name=request.library_name,
            tmdb_api_key=os.getenv('TMDB_API_KEY'),
            omdb_api_key=os.getenv('OMDB_API_KEY'),
            mdblist_api_key=os.getenv('MDBLIST_API_KEY'),
            backup_dir='/backups',
            dry_run=False,
            rating_sources=request.rating_sources,
            badge_style=request.badge_style  # Pass badge styling options
        )

        # Load excluded items from settings
        process_settings = _load_settings()
        excluded = process_settings.get('excluded_items', {}).get(request.library_name, [])
        manager._excluded_items = set(excluded)

        if request.rating_key:
            all_items = [manager.library.fetchItem(int(request.rating_key))]
        else:
            all_items = manager.library.all()
            if request.limit:
                all_items = all_items[:request.limit]

        processing_state["total"] = len(all_items)

        num_workers = max(1, min(10, request.workers))
        logger.info(f"🎬 Processing started: {request.library_name} ({len(all_items)} items, {num_workers} workers)")

        def _process_single(item):
            """Process a single item in a thread worker."""
            if request.badge_positions:
                return manager.process_movie(
                    item,
                    position=request.position,
                    force=request.force,
                    badge_positions=request.badge_positions
                )
            else:
                position_param = request.badge_position if request.badge_position else request.position
                return manager.process_movie(item, position=position_param, force=request.force)

        progress_counter = 0
        loop = asyncio.get_event_loop()

        with ThreadPoolExecutor(max_workers=num_workers) as executor:

            async def _run_item(item):
                """Wrap executor call to return (item, result) tuple."""
                try:
                    result = await loop.run_in_executor(executor, _process_single, item)
                    return item, result
                except Exception as e:
                    logger.error(f"✗ {item.title}: Worker error - {e}")
                    return item, False

            tasks = [_run_item(item) for item in all_items]

            for coro in asyncio.as_completed(tasks):
                if processing_state["stop_requested"]:
                    logger.info(f"Stop requested - stopping processing")
                    break

                item, result = await coro

                progress_counter += 1
                processing_state["progress"] = progress_counter
                processing_state["current_item"] = item.title

                # Handle three-state return: True=success, None=skip, False=fail
                if result is None:
                    processing_state["skipped"] += 1
                elif result:
                    processing_state["success"] += 1
                else:
                    processing_state["failed"] += 1

                # Broadcast progress to all WebSocket connections
                await broadcast_progress()

        processing_state["is_processing"] = False
        processing_state["stop_requested"] = False

        # Calculate duration and stats
        duration = datetime.now() - processing_start_time
        duration_seconds = duration.total_seconds()
        duration_str = f"{int(duration_seconds // 3600)}h {int((duration_seconds % 3600) // 60)}m {int(duration_seconds % 60)}s" if duration_seconds >= 3600 else f"{int(duration_seconds // 60)}m {int(duration_seconds % 60)}s"

        total = processing_state["total"]
        success = processing_state["success"]
        failed = processing_state["failed"]
        skipped = processing_state["skipped"]

        success_rate = (success / total * 100) if total > 0 else 0
        failed_rate = (failed / total * 100) if total > 0 else 0
        skipped_rate = (skipped / total * 100) if total > 0 else 0
        rate_per_min = (total / (duration_seconds / 60)) if duration_seconds > 0 else 0

        # Log fancy summary
        logger.info("=" * 60)
        logger.info(f"✅ Processing Completed: {request.library_name}")
        logger.info("-" * 60)
        logger.info(f"Total Items:     {total}")
        logger.info(f"Success:         {success} ({success_rate:.1f}%)")
        logger.info(f"Failed:          {failed} ({failed_rate:.1f}%)")
        logger.info(f"Skipped:         {skipped} ({skipped_rate:.1f}%)")
        logger.info(f"Duration:        {duration_str}")
        logger.info(f"Rate:            {rate_per_min:.1f} items/min")
        logger.info("=" * 60)

        # Record to run history
        _record_run('process', request.library_name, total, success, failed, skipped, duration_seconds, force=request.force)

        await broadcast_progress()  # Final update

    except Exception as e:
        import traceback
        processing_state["is_processing"] = False
        processing_state["stop_requested"] = False
        processing_state["error"] = str(e)
        logger.error(f"❌ Processing failed: {request.library_name} - Error: {e}")
        logger.error(traceback.format_exc())  # Print full traceback
        await broadcast_progress()


@app.get("/api/status")
async def get_status():
    """Get current processing status"""
    return processing_state


# ── Run History ───────────────────────────────────────────────────────────────

@app.get("/api/history")
async def get_history(limit: int = 50):
    """Get processing run history"""
    entries = _load_history()
    return {"history": entries[-limit:]}


@app.delete("/api/history")
async def clear_history():
    """Clear run history"""
    _save_history([])
    return {"status": "cleared"}


# ── Badge Templates ───────────────────────────────────────────────────────────

@app.get("/api/badge-templates")
async def get_badge_templates():
    """Return available badge templates for the frontend selector"""
    from src.rating_overlay.multi_rating_badge import BADGE_TEMPLATES
    templates = {
        key: {"label": t["label"], "description": t["description"]}
        for key, t in BADGE_TEMPLATES.items()
    }
    return {"templates": templates}


# ── Health Dashboard ──────────────────────────────────────────────────────────

@app.get("/api/health")
async def get_health():
    """Health check with API key status, Plex connection, backup disk usage"""
    result = {
        'plex': {'status': 'unknown', 'server_name': None, 'version': None},
        'api_keys': {},
        'backups': {'total_size_bytes': 0, 'total_size_human': '0 B', 'library_count': 0, 'item_count': 0},
        'last_run': None,
        'next_scheduled': {'normal': None, 'force': None},
    }

    # Plex connection
    try:
        from plexapi.server import PlexServer
        plex_url = os.getenv('PLEX_URL', '')
        plex_token = os.getenv('PLEX_TOKEN', '')
        if plex_url and plex_token:
            server = PlexServer(plex_url, plex_token, timeout=5)
            result['plex'] = {'status': 'connected', 'server_name': server.friendlyName, 'version': server.version}
        else:
            result['plex'] = {'status': 'not_configured', 'server_name': None, 'version': None}
    except Exception as e:
        result['plex'] = {'status': 'error', 'error': str(e), 'server_name': None, 'version': None}

    # API keys
    key_checks = {
        'tmdb': ('TMDB_API_KEY', {'', 'YOUR_TMDB_KEY', 'YOUR_TMDB_API_KEY'}),
        'omdb': ('OMDB_API_KEY', {'', 'YOUR_OMDB_KEY', 'YOUR_OMDB_API_KEY', 'YOUR_OMDB_API_KEY_HERE'}),
        'mdblist': ('MDBLIST_API_KEY', {'', 'YOUR_MDBLIST_KEY', 'YOUR_MDBLIST_API_KEY', 'YOUR_MDBLIST_API_KEY_HERE'}),
    }
    for name, (env_var, placeholders) in key_checks.items():
        val = os.getenv(env_var, '')
        if not val:
            result['api_keys'][name] = 'missing'
        elif val.strip().upper() in {p.upper() for p in placeholders}:
            result['api_keys'][name] = 'placeholder'
        else:
            result['api_keys'][name] = 'configured'

    # Validate TMDB key
    if result['api_keys'].get('tmdb') == 'configured':
        try:
            import requests as req
            tmdb_key = os.getenv('TMDB_API_KEY', '')
            if tmdb_key.startswith('eyJ'):
                resp = req.get('https://api.themoviedb.org/3/configuration', headers={'Authorization': f'Bearer {tmdb_key}'}, timeout=5)
            else:
                resp = req.get(f'https://api.themoviedb.org/3/configuration?api_key={tmdb_key}', timeout=5)
            if resp.status_code == 200:
                result['api_keys']['tmdb'] = 'valid'
            else:
                result['api_keys']['tmdb'] = 'invalid'
        except Exception:
            result['api_keys']['tmdb'] = 'configured'

    # Backup disk usage
    backup_root = Path('/backups')
    if backup_root.exists():
        total_size = 0
        item_count = 0
        lib_count = 0
        for lib_dir in backup_root.iterdir():
            if lib_dir.is_dir():
                lib_count += 1
                for item_dir in lib_dir.iterdir():
                    if item_dir.is_dir():
                        item_count += 1
                        for f in item_dir.iterdir():
                            if f.is_file():
                                total_size += f.stat().st_size
        if total_size >= 1073741824:
            human = f"{total_size / 1073741824:.1f} GB"
        elif total_size >= 1048576:
            human = f"{total_size / 1048576:.1f} MB"
        elif total_size >= 1024:
            human = f"{total_size / 1024:.1f} KB"
        else:
            human = f"{total_size} B"
        result['backups'] = {'total_size_bytes': total_size, 'total_size_human': human, 'library_count': lib_count, 'item_count': item_count}

    # Last run & next scheduled
    history = _load_history()
    if history:
        result['last_run'] = history[-1]
    for key in ('cron_normal', 'cron_force'):
        job = scheduler.get_job(key)
        sched_key = 'normal' if 'normal' in key else 'force'
        result['next_scheduled'][sched_key] = job.next_run_time.isoformat() if job and job.next_run_time else None

    return result


# ── Item Gallery ──────────────────────────────────────────────────────────────

@app.get("/api/gallery/{library_name}")
async def get_gallery(library_name: str, page: int = 1, per_page: int = 50):
    """Get item gallery with overlay status for a library"""
    from src.rating_overlay.backup_manager import PosterBackupManager

    backup_manager = PosterBackupManager(backup_dir='/backups')
    backup_root = Path('/backups') / library_name

    items = []
    if backup_root.exists():
        all_dirs = sorted([d for d in backup_root.iterdir() if d.is_dir()], key=lambda d: d.name)
        total = len(all_dirs)
        start = (page - 1) * per_page
        page_dirs = all_dirs[start:start + per_page]

        settings = _load_settings()
        excluded = settings.get('excluded_items', {}).get(library_name, [])

        for item_dir in page_dirs:
            has_original = (item_dir / 'poster_original.jpg').exists()
            has_overlay = (item_dir / 'poster_overlay.jpg').exists()
            metadata = backup_manager._load_metadata(item_dir)

            status = 'overlay_applied' if has_overlay else ('backup_only' if has_original else 'unknown')
            if item_dir.name in excluded:
                status = 'excluded'

            items.append({
                'title': item_dir.name,
                'status': status,
                'ratings': metadata.get('ratings', {}) if metadata else {},
                'year': metadata.get('year') if metadata else None,
                'rating_key': metadata.get('rating_key') if metadata else None,
                'has_original': has_original,
                'has_overlay': has_overlay,
            })
    else:
        total = 0

    return {'items': items, 'total': total, 'page': page, 'per_page': per_page, 'pages': max(1, -(-total // per_page))}


@app.get("/api/gallery/{library_name}/{item_title}/poster")
async def get_gallery_poster(library_name: str, item_title: str, version: str = 'overlay'):
    """Serve poster image for gallery thumbnail"""
    safe_title = "".join(c for c in item_title if c.isalnum() or c in (' ', '-', '_')).strip()
    filename = 'poster_overlay.jpg' if version == 'overlay' else 'poster_original.jpg'
    poster_path = Path('/backups') / library_name / safe_title / filename

    if not poster_path.exists():
        alt = 'poster_original.jpg' if version == 'overlay' else 'poster_overlay.jpg'
        poster_path = Path('/backups') / library_name / safe_title / alt

    if poster_path.exists():
        return FileResponse(str(poster_path), media_type='image/jpeg')
    return {"error": "not found"}


@app.post("/api/gallery/{library_name}/{item_title}/exclude")
async def exclude_item(library_name: str, item_title: str):
    """Exclude an item from future processing"""
    settings = _load_settings()
    excluded = settings.setdefault('excluded_items', {}).setdefault(library_name, [])
    safe_title = "".join(c for c in item_title if c.isalnum() or c in (' ', '-', '_')).strip()
    if safe_title not in excluded:
        excluded.append(safe_title)
    _save_settings(settings)
    return {"status": "excluded", "title": safe_title}


@app.delete("/api/gallery/{library_name}/{item_title}/exclude")
async def unexclude_item(library_name: str, item_title: str):
    """Remove item from exclude list"""
    settings = _load_settings()
    excluded = settings.get('excluded_items', {}).get(library_name, [])
    safe_title = "".join(c for c in item_title if c.isalnum() or c in (' ', '-', '_')).strip()
    if safe_title in excluded:
        excluded.remove(safe_title)
    _save_settings(settings)
    return {"status": "included", "title": safe_title}


@app.post("/api/gallery/{library_name}/{item_title}/retry")
async def retry_item(library_name: str, item_title: str):
    """Retry processing a single item by title"""
    try:
        from plexapi.server import PlexServer

        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')
        server = PlexServer(plex_url, plex_token)
        library = server.library.section(library_name)

        results = library.search(title=item_title)
        if not results:
            return {"error": f"Item '{item_title}' not found in Plex library"}

        item = results[0]
        settings = _load_settings()

        asyncio.create_task(process_library_background(ProcessRequest(
            library_name=library_name,
            rating_key=str(item.ratingKey),
            force=True,
            badge_style=settings.get("badge_style"),
            badge_positions=settings.get("badge_positions"),
            rating_sources=settings.get("rating_sources"),
        )))
        return {"status": "started", "title": item.title}
    except Exception as e:
        return {"error": str(e)}


class PreviewRequest(BaseModel):
    library_name: str
    badge_positions: Optional[Dict[str, Dict[str, float]]] = None
    rating_sources: Optional[Dict[str, bool]] = None
    badge_style: Optional[Dict[str, Any]] = None
    count: int = 3


@app.post("/api/preview")
async def preview_posters(request: PreviewRequest):
    """
    Render overlaid posters for a random sample of library items.
    Returns base64 images — no Plex upload, no backup.
    """
    import random
    import base64
    import requests as req
    from pathlib import Path
    import time

    try:
        manager = PlexPosterManager(
            plex_url=os.getenv('PLEX_URL'),
            plex_token=os.getenv('PLEX_TOKEN'),
            library_name=request.library_name,
            tmdb_api_key=os.getenv('TMDB_API_KEY'),
            omdb_api_key=os.getenv('OMDB_API_KEY'),
            mdblist_api_key=os.getenv('MDBLIST_API_KEY'),
            backup_dir='/backups',
            dry_run=False,
            rating_sources=request.rating_sources,
            badge_style=request.badge_style,
        )

        all_items = manager.library.all()
        candidate_count = min(len(all_items), max(request.count * 20, 120))
        sample = random.sample(all_items, candidate_count) if len(all_items) > candidate_count else list(all_items)
        random.shuffle(sample)
        started = time.monotonic()
        max_runtime_seconds = 20

        debug = {
            'total_items': len(all_items),
            'sampled': 0,
            'returned': 0,
            'skipped_no_ids': 0,
            'skipped_no_ratings': 0,
            'skipped_no_poster': 0,
            'skipped_download_failed': 0,
            'skipped_render_failed': 0,
        }

        results = []
        for item in sample:
            if len(results) >= request.count:
                break

            if (time.monotonic() - started) > max_runtime_seconds:
                logger.warning(f"Preview timeout budget reached for {request.library_name} after {debug['sampled']} items")
                break

            debug['sampled'] += 1

            try:
                # Fetch ratings using same priority order as process_movie
                plex_ratings = manager._extract_plex_ratings(item)
                tmdb_id = manager._extract_tmdb_id(item.guids)
                imdb_id = manager._extract_imdb_id(item.guids)

                if not tmdb_id and not imdb_id:
                    debug['skipped_no_ids'] += 1
                    continue

                ratings = {}

                # Priority 1: Plex ratings
                for key in ('tmdb', 'imdb', 'rt_critic', 'rt_audience'):
                    if key in plex_ratings:
                        ratings[key] = plex_ratings[key]

                # Priority 2: API fallback for missing ratings
                media_type = 'tv' if manager.library.type == 'show' else 'movie'
                tmdb_status = None
                if tmdb_id:
                    tmdb_data = manager.rating_fetcher.fetch_tmdb_rating(tmdb_id, media_type=media_type)
                    if tmdb_data:
                        tmdb_status = tmdb_data.get('status')
                        if 'tmdb' not in ratings and tmdb_data.get('rating', 0) > 0:
                            ratings['tmdb'] = tmdb_data['rating']

                if imdb_id:
                    if 'imdb' not in ratings:
                        omdb_data = manager.rating_fetcher.fetch_omdb_rating(imdb_id)
                        if omdb_data and omdb_data.get('imdb_rating'):
                            try:
                                ratings['imdb'] = float(omdb_data['imdb_rating'])
                            except Exception:
                                pass

                    if 'rt_critic' not in ratings or 'rt_audience' not in ratings:
                        mdb_data = manager.rating_fetcher.fetch_mdblist_rating(imdb_id)
                        if mdb_data:
                            if 'rt_critic' not in ratings and mdb_data.get('rt_critic'):
                                ratings['rt_critic'] = mdb_data['rt_critic']
                            if 'rt_audience' not in ratings and mdb_data.get('rt_audience'):
                                ratings['rt_audience'] = mdb_data['rt_audience']

                if request.rating_sources:
                    ratings = {k: v for k, v in ratings.items() if request.rating_sources.get(k, True)}

                selected_status = str((request.badge_style or {}).get('status_overlay', 'none')).strip().lower()
                if not ratings or all(v == 0 for v in ratings.values()):
                    if selected_status == 'none':
                        debug['skipped_no_ratings'] += 1
                        continue

                # Use existing backup poster if available, otherwise download
                poster_path = manager.backup_manager.get_original_poster(manager.library_name, item.title)

                if not poster_path:
                    poster_url = item.posterUrl
                    if not poster_url:
                        debug['skipped_no_poster'] += 1
                        continue
                    response = req.get(
                        poster_url,
                        headers={'X-Plex-Token': manager.plex_token},
                        timeout=15
                    )
                    if response.status_code != 200:
                        debug['skipped_download_failed'] += 1
                        continue
                    tmp_src = Path(f'/tmp/kometizarr_prev_src_{item.ratingKey}.jpg')
                    tmp_src.write_bytes(response.content)
                    poster_path = str(tmp_src)

                # Apply overlay (no upload)
                output_path = f'/tmp/kometizarr_prev_{item.ratingKey}.jpg'
                effective_badge_style = manager._build_effective_badge_style(item, tmdb_id=tmdb_id, tmdb_status=tmdb_status)
                applied_status_overlay = effective_badge_style.get('status_overlay', 'none')
                logger.info(f"Preview '{item.title}': tmdb_id={tmdb_id}, imdb_id={imdb_id}, status_overlay={applied_status_overlay}")
                manager.multi_rating_badge.apply_to_poster(
                    poster_path=str(poster_path),
                    ratings=ratings,
                    output_path=output_path,
                    badge_style=effective_badge_style,
                    badge_positions=request.badge_positions,
                )

                with open(output_path, 'rb') as f:
                    image_b64 = base64.b64encode(f.read()).decode()

                results.append({
                    'title': item.title,
                    'year': getattr(item, 'year', None),
                    'ratings': ratings,
                    'status_overlay': applied_status_overlay,
                    'image': image_b64,
                })
                debug['returned'] = len(results)

            except Exception as e:
                logger.warning(f"Preview skipped for {item.title}: {e}")
                debug['skipped_render_failed'] += 1
                continue

        if not results:
            logger.info(f"Preview debug for {request.library_name}: {debug}")

        return {'previews': results, 'debug': debug}

    except Exception as e:
        logger.error(f"Preview failed: {e}")
        return {'error': str(e), 'previews': []}


@app.websocket("/ws/progress")
async def websocket_progress(websocket: WebSocket):
    """WebSocket endpoint for live progress updates"""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        # Send initial state
        await websocket.send_json(processing_state)

        # Keep connection alive
        while True:
            await asyncio.sleep(1)
            # Client can send ping to keep alive
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        active_connections.remove(websocket)


async def broadcast_progress():
    """Broadcast progress to all connected WebSocket clients"""
    for connection in active_connections:
        try:
            await connection.send_json(processing_state)
        except:
            active_connections.remove(connection)


async def broadcast_restore_progress():
    """Broadcast restore progress to all connected WebSocket clients"""
    for connection in active_connections:
        try:
            await connection.send_json(restore_state)
        except:
            active_connections.remove(connection)


@app.get("/api/restore/status")
async def get_restore_status():
    """Get current restore status"""
    return restore_state


# Collection Management Endpoints

@app.get("/api/collections")
async def get_collections(library_name: str):
    """Get all collections in a library - optimized for speed"""
    try:
        from plexapi.server import PlexServer

        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')

        server = PlexServer(plex_url, plex_token)
        library = server.library.section(library_name)

        collections = []
        # Use search() instead of collections() - much faster as it doesn't load full metadata
        for collection in library.search(libtype='collection'):
            collections.append({
                "title": collection.title,
                # Use childCount instead of len(items()) - avoids fetching all items
                "count": collection.childCount if hasattr(collection, 'childCount') else 0,
                "summary": collection.summary if hasattr(collection, 'summary') else ""
            })

        return {"collections": collections}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/collections/{collection_title}/items")
async def get_collection_items(collection_title: str, library_name: str):
    """Get first 10 items in a collection for preview"""
    try:
        from plexapi.server import PlexServer

        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')

        server = PlexServer(plex_url, plex_token)
        library = server.library.section(library_name)

        # Get the collection
        collection = library.collection(collection_title)

        # Get total count
        total_count = collection.childCount if hasattr(collection, 'childCount') else 0

        # Get just first 10 items for preview
        items = []
        limit = 10

        for i, item in enumerate(collection.items()):
            if i >= limit:
                break
            items.append({
                "title": item.title,
                "year": item.year if hasattr(item, 'year') else None,
                "rating": round(item.rating, 1) if hasattr(item, 'rating') and item.rating else None
            })

        return {
            "items": items,
            "total": total_count,
            "showing": len(items),
            "has_more": total_count > len(items)
        }
    except Exception as e:
        return {"error": str(e)}


class DecadeCollectionRequest(BaseModel):
    library_name: str
    decades: List[Dict]  # [{"title": "1980s Movies", "start": 1980, "end": 1989}, ...]


class StudioCollectionRequest(BaseModel):
    library_name: str
    studios: List[Dict]  # [{"title": "Marvel", "studios": ["Marvel Studios"]}, ...]


class KeywordCollectionRequest(BaseModel):
    library_name: str
    keywords: List[Dict]  # [{"title": "DC Universe", "keywords": ["dc comics", "batman"]}, ...]


@app.post("/api/collections/decade")
async def create_decade_collections(request: DecadeCollectionRequest):
    """Create decade collections"""
    try:
        manager = CollectionManager(
            plex_url=os.getenv('PLEX_URL'),
            plex_token=os.getenv('PLEX_TOKEN'),
            library_name=request.library_name,
            dry_run=False
        )

        collections = manager.create_decade_collections(request.decades)

        return {
            "status": "success",
            "created": len(collections),
            "collections": [c.title for c in collections]
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/collections/studio")
async def create_studio_collections(request: StudioCollectionRequest):
    """Create studio collections"""
    try:
        manager = CollectionManager(
            plex_url=os.getenv('PLEX_URL'),
            plex_token=os.getenv('PLEX_TOKEN'),
            library_name=request.library_name,
            dry_run=False
        )

        collections = manager.create_studio_collections(request.studios)

        return {
            "status": "success",
            "created": len(collections),
            "collections": [c.title for c in collections]
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/collections/keyword")
async def create_keyword_collections(request: KeywordCollectionRequest):
    """Create keyword collections"""
    try:
        manager = CollectionManager(
            plex_url=os.getenv('PLEX_URL'),
            plex_token=os.getenv('PLEX_TOKEN'),
            library_name=request.library_name,
            tmdb_api_key=os.getenv('TMDB_API_KEY'),
            dry_run=False
        )

        collections = manager.create_keyword_collections(request.keywords)

        return {
            "status": "success",
            "created": len(collections),
            "collections": [c.title for c in collections]
        }
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/collections/{collection_title}")
async def delete_collection(collection_title: str, library_name: str):
    """Delete a collection"""
    try:
        from plexapi.server import PlexServer

        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')

        server = PlexServer(plex_url, plex_token)
        library = server.library.section(library_name)

        # Get the collection
        collection = library.collection(collection_title)

        # Delete it
        collection.delete()

        return {"status": "success", "message": f"Deleted collection: {collection_title}"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/library/{library_name}/studios")
async def get_library_studios(library_name: str):
    """Get all unique studios/networks in a library (for debugging)"""
    try:
        from plexapi.server import PlexServer

        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')

        server = PlexServer(plex_url, plex_token)
        library = server.library.section(library_name)

        # Get all items
        all_items = library.all()

        # For TV shows, use 'network' field; for movies, use 'studio' field
        is_tv = library.type == 'show'
        field_name = 'network' if is_tv else 'studio'

        # Collect all unique studios/networks
        studios = {}
        for item in all_items:
            if is_tv:
                # TV shows - check network field
                if hasattr(item, 'network') and item.network:
                    value = item.network
                    if value not in studios:
                        studios[value] = 0
                    studios[value] += 1
            else:
                # Movies - check studio field
                if hasattr(item, 'studio') and item.studio:
                    value = item.studio
                    if value not in studios:
                        studios[value] = 0
                    studios[value] += 1

        # Sort by count descending
        sorted_studios = sorted(studios.items(), key=lambda x: x[1], reverse=True)

        return {
            "library": library_name,
            "field": field_name,
            "total_items": len(all_items),
            "studios": [{"name": name, "count": count} for name, count in sorted_studios]
        }
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Settings, Fresh Posters, Delete Backups, Cron, Webhook
# ─────────────────────────────────────────────────────────────────────────────

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

SETTINGS_PATH = Path('/app/kometizarr/data/settings.json')

scheduler = AsyncIOScheduler()

# Settings schema version — increment when adding/removing keys
SETTINGS_SCHEMA_VERSION = 2

SETTINGS_SCHEMA_DEFAULTS = {
    "_schema_version": SETTINGS_SCHEMA_VERSION,
    "cron_normal": {"enabled": False, "libraries": [], "schedule": "0 3 * * *"},
    "cron_force":  {"enabled": False, "libraries": [], "schedule": "0 3 * * 0"},
    "webhook": {"enabled": False, "libraries": []},
    "webhook_delay": 15,
    "excluded_items": {},
    "badge_positions": None,  # Seeded separately in startup
    "badge_style": None,
    "rating_sources": None,
    "selected_libraries": [],
    "per_type_positions": None,
    "per_type_style": None,
    "per_type_sources": None,
}

# Valid top-level keys (stale keys not in this set are pruned)
VALID_SETTINGS_KEYS = set(SETTINGS_SCHEMA_DEFAULTS.keys())

fresh_posters_state = {
    "is_running": False,
    "library": None,
    "progress": 0,
    "total": 0,
    "restored": 0,
    "failed": 0,
    "current_item": None,
}


def _load_settings() -> dict:
    defaults = {
        "cron_normal": {"enabled": False, "libraries": [], "schedule": "0 3 * * *"},
        "cron_force":  {"enabled": False, "libraries": [], "schedule": "0 3 * * 0"},
        "webhook": {"enabled": False, "libraries": []},
        "webhook_delay": 15,
        "excluded_items": {},
    }
    if not SETTINGS_PATH.exists():
        return defaults
    data = json.loads(SETTINGS_PATH.read_text())
    # Migrate old single-library format
    for key in ("cron_normal", "cron_force"):
        block = data.get(key, {})
        if "library" in block and "libraries" not in block:
            old = block.pop("library")
            block["libraries"] = [] if not old or old == "__all__" else [old]
    if "webhook" in data and "library" in data["webhook"] and "libraries" not in data["webhook"]:
        old = data["webhook"].pop("library")
        data["webhook"]["enabled"] = bool(old)
        data["webhook"]["libraries"] = [] if not old or old == "__all__" else [old]
    # Ensure new keys have defaults
    if "webhook_delay" not in data:
        data["webhook_delay"] = 15
    if "excluded_items" not in data:
        data["excluded_items"] = {}
    return data


def _validate_and_migrate_settings(settings: dict) -> dict:
    """Validate settings schema, add missing keys, prune stale ones."""
    stored_version = settings.get('_schema_version', 1)

    # Add any missing keys from defaults
    for key, default in SETTINGS_SCHEMA_DEFAULTS.items():
        if key not in settings and default is not None:
            settings[key] = default

    # Prune stale keys (not in schema)
    stale = [k for k in settings if k not in VALID_SETTINGS_KEYS]
    for k in stale:
        del settings[k]
        logger.info(f"Settings: pruned stale key '{k}'")

    # Ensure nested structures
    if not isinstance(settings.get('webhook_delay'), (int, float)):
        settings['webhook_delay'] = 15
    settings['webhook_delay'] = max(0, min(120, int(settings['webhook_delay'])))

    if not isinstance(settings.get('excluded_items'), dict):
        settings['excluded_items'] = {}

    settings['_schema_version'] = SETTINGS_SCHEMA_VERSION
    return settings


def _save_settings(settings: dict):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


def _add_cron_job(scheduler, job_id: str, schedule: str, libraries: list, force: bool):
    parts = schedule.split()
    if len(parts) != 5:
        return
    trigger = CronTrigger(
        minute=parts[0], hour=parts[1],
        day=parts[2], month=parts[3], day_of_week=parts[4]
    )
    scheduler.add_job(
        _cron_run_libraries,
        trigger=trigger,
        args=[libraries, force],
        id=job_id,
        replace_existing=True,
    )
    label = ", ".join(libraries) if libraries else "all"
    logger.info(f"Cron [{job_id}] scheduled: {schedule} for [{label}] (force={force})")


def _reschedule_cron(settings: dict):
    """Apply both cron configs to the scheduler."""
    scheduler.remove_all_jobs()
    for key, force in [("cron_normal", False), ("cron_force", True)]:
        cron = settings.get(key, {})
        if cron.get("enabled") and cron.get("schedule"):
            try:
                _add_cron_job(scheduler, key, cron["schedule"], cron.get("libraries", []), force)
            except Exception as e:
                logger.error(f"Failed to schedule {key}: {e}")


async def _run_libraries_sequentially(libraries: list, force: bool):
    """Fetch all Plex library names if list is empty, then process each sequentially."""
    if not libraries:
        try:
            from plexapi.server import PlexServer
            server = PlexServer(os.getenv('PLEX_URL'), os.getenv('PLEX_TOKEN'))
            libraries = [lib.title for lib in server.library.sections()]
        except Exception as e:
            logger.error(f"Cron: failed to fetch library list: {e}")
            return
    settings = _load_settings()
    per_type_positions = settings.get("per_type_positions")
    per_type_style = settings.get("per_type_style")
    per_type_sources = settings.get("per_type_sources")
    # Fallback flat settings
    flat_badge_style = settings.get("badge_style")
    flat_badge_positions = settings.get("badge_positions")
    flat_rating_sources = settings.get("rating_sources")
    label = "force" if force else "normal"
    for lib_name in libraries:
        lib_type = _get_library_type(lib_name)
        type_key = 'tv' if lib_type == 'show' else 'movie'

        bs = (per_type_style or {}).get(type_key, flat_badge_style)
        bp = (per_type_positions or {}).get(type_key, flat_badge_positions)
        rs = (per_type_sources or {}).get(type_key, flat_rating_sources)

        # Filter badge_positions to only enabled sources
        if bp and rs:
            bp = {k: v for k, v in bp.items() if rs.get(k, True)}

        logger.info(f"Cron ({label}): processing {lib_name} (type={type_key})")
        await process_library_background(ProcessRequest(
            library_name=lib_name,
            force=force,
            badge_style=bs,
            badge_positions=bp,
            rating_sources=rs,
        ))


async def _cron_run_libraries(libraries: list, force: bool = False):
    """Called by APScheduler — starts processing if not already running."""
    if processing_state["is_processing"]:
        logger.info("Cron: skipping, processing already in progress")
        return
    asyncio.create_task(_run_libraries_sequentially(libraries, force))


async def _webhook_queue_worker():
    """Processes webhook-queued items one at a time, waiting if processing is busy."""
    while True:
        library_name, rating_key, item_title = await webhook_queue.get()
        try:
            # Wait if processing is already running (e.g. cron or manual run)
            while processing_state["is_processing"]:
                await asyncio.sleep(2)

            # Delay to let Plex finish metadata matching (GUIDs aren't available immediately)
            settings = _load_settings()
            webhook_delay = settings.get('webhook_delay', 15)
            logger.info(f"Webhook queue: waiting {webhook_delay}s for Plex to populate metadata for {item_title}")
            await asyncio.sleep(webhook_delay)

            # Load current badge settings — resolve per-type
            per_type_positions = settings.get("per_type_positions")
            per_type_style = settings.get("per_type_style")
            per_type_sources = settings.get("per_type_sources")

            lib_type = _get_library_type(library_name)
            type_key = 'tv' if lib_type == 'show' else 'movie'

            badge_style = (per_type_style or {}).get(type_key, settings.get("badge_style"))
            badge_positions = (per_type_positions or {}).get(type_key, settings.get("badge_positions"))
            rating_sources = (per_type_sources or {}).get(type_key, settings.get("rating_sources"))

            if badge_positions and rating_sources:
                badge_positions = {k: v for k, v in badge_positions.items() if rating_sources.get(k, True)}

            logger.info(f"Webhook queue: processing {library_name} / {item_title} (key={rating_key}, type={type_key})")
            await process_library_background(ProcessRequest(
                library_name=library_name,
                rating_key=rating_key,
                force=True,  # Always apply overlay for webhook items
                badge_style=badge_style,
                badge_positions=badge_positions,
                rating_sources=rating_sources,
            ))
        except Exception as e:
            logger.error(f"Webhook queue worker error: {e}")
        finally:
            webhook_queue.task_done()


DEFAULT_BADGE_POSITIONS = {
    "tmdb":        {"x": 2,  "y": 2},
    "imdb":        {"x": 70, "y": 2},
    "rt_critic":   {"x": 2,  "y": 78},
    "rt_audience": {"x": 70, "y": 78},
}

DEFAULT_BADGE_STYLE = {
    "individual_badge_size": 12,
    "font_size_multiplier": 1.0,
    "logo_size_multiplier": 1.0,
    "rating_color": "#FFD700",
    "background_opacity": 128,
    "font_family": "DejaVu Sans Bold",
    "status_overlay": "none",
    "status_position": {"x": 50, "y": 50},
    "status_rotation": 0,
}

DEFAULT_RATING_SOURCES = {
    "tmdb": True, "imdb": True, "rt_critic": True, "rt_audience": True,
}


@app.on_event("startup")
async def startup_event():
    scheduler.start()
    settings = _load_settings()
    # Validate and migrate settings schema
    settings = _validate_and_migrate_settings(settings)
    # Seed badge defaults so webhook/cron work out of the box without UI interaction
    changed = False
    if "badge_positions" not in settings or settings.get("badge_positions") is None:
        settings["badge_positions"] = DEFAULT_BADGE_POSITIONS
        changed = True
    if "badge_style" not in settings or settings.get("badge_style") is None:
        settings["badge_style"] = DEFAULT_BADGE_STYLE
        changed = True
    else:
        for key, value in DEFAULT_BADGE_STYLE.items():
            if key not in settings["badge_style"]:
                settings["badge_style"][key] = value
                changed = True
    if "rating_sources" not in settings or settings.get("rating_sources") is None:
        settings["rating_sources"] = DEFAULT_RATING_SOURCES
        changed = True
    if changed:
        _save_settings(settings)
    _reschedule_cron(settings)
    asyncio.create_task(_webhook_queue_worker())


@app.get("/api/settings")
async def get_settings():
    settings = _load_settings()
    for key in ("cron_normal", "cron_force"):
        job = scheduler.get_job(key)
        settings.setdefault(key, {})["next_run"] = job.next_run_time.isoformat() if job and job.next_run_time else None
    return settings


@app.put("/api/settings")
async def update_settings(settings: dict):
    settings = _validate_and_migrate_settings(settings)
    _save_settings(settings)
    _reschedule_cron(settings)
    result = {"status": "saved"}
    for key in ("cron_normal", "cron_force"):
        job = scheduler.get_job(key)
        result[f"{key}_next_run"] = job.next_run_time.isoformat() if job and job.next_run_time else None
    return result


# ── Fresh Posters ─────────────────────────────────────────────────────────────

class FreshPostersRequest(BaseModel):
    library_name: str


@app.post("/api/fetch-fresh-posters")
async def start_fetch_fresh_posters(request: FreshPostersRequest):
    global fresh_posters_state
    if fresh_posters_state["is_running"]:
        return {"error": "Already running"}
    asyncio.create_task(_fetch_fresh_posters_task(request.library_name))
    return {"status": "started"}


@app.get("/api/fetch-fresh-posters/status")
async def get_fresh_posters_status():
    return fresh_posters_state


async def _fetch_fresh_posters_task(library_name: str):
    global fresh_posters_state
    fresh_posters_state.update({
        "is_running": True, "library": library_name,
        "progress": 0, "total": 0,
        "restored": 0, "failed": 0, "current_item": None,
    })
    try:
        from plexapi.server import PlexServer
        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')
        server = PlexServer(plex_url, plex_token)
        library = server.library.section(library_name)
        all_items = library.all()
        fresh_posters_state["total"] = len(all_items)
        logger.info(f"Fetch Fresh Posters: {library_name} ({len(all_items)} items)")

        for i, item in enumerate(all_items, 1):
            fresh_posters_state["progress"] = i
            fresh_posters_state["current_item"] = item.title
            try:
                posters = item.posters()
                original = next((p for p in posters if 'upload' not in p.ratingKey), None)
                if original:
                    original.select()
                    fresh_posters_state["restored"] += 1
                    logger.debug(f"✓ {item.title}: reset to original poster")
                else:
                    fresh_posters_state["failed"] += 1
            except Exception as e:
                fresh_posters_state["failed"] += 1
                logger.warning(f"Failed for {item.title}: {e}")
            await asyncio.sleep(0.05)

        logger.info(f"Fresh Posters done: {fresh_posters_state['restored']} restored, {fresh_posters_state['failed']} failed")
    except Exception as e:
        logger.error(f"Fetch Fresh Posters failed: {e}")
    finally:
        fresh_posters_state["is_running"] = False
        fresh_posters_state["current_item"] = None


# ── Delete Backups ────────────────────────────────────────────────────────────

@app.delete("/api/backups")
async def delete_backups(library_name: str, confirm: str = ""):
    if confirm != "DELETE":
        return {"error": "Must pass confirm=DELETE"}
    import shutil
    backup_dir = Path("/backups") / library_name
    if not backup_dir.exists():
        return {"error": f"No backups found for {library_name}"}
    try:
        item_count = sum(1 for _ in backup_dir.iterdir())
        shutil.rmtree(backup_dir)
        logger.info(f"Deleted backups for {library_name} ({item_count} items)")
        return {"status": "deleted", "items": item_count}
    except Exception as e:
        return {"error": str(e)}


# ── Plex Webhook ──────────────────────────────────────────────────────────────

from fastapi import Form as FastAPIForm, Request as FastAPIRequest


@app.post("/webhook/plex")
async def plex_webhook(request: FastAPIRequest):
    """Receive Plex webhooks — triggers processing on library.new events.

    Supports two formats:
    - Plex native: multipart/form-data with a 'payload' field containing JSON
    - Tautulli / JSON clients: application/json body
    """
    try:
        content_type = request.headers.get("content-type", "")

        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            raw_payload = form.get("payload", "{}")
            # Plex sends payload as an UploadFile in multipart; read its bytes
            if hasattr(raw_payload, 'read'):
                raw_payload = (await raw_payload.read()).decode('utf-8')
            data = json.loads(raw_payload)
        else:
            body = await request.body()
            data = json.loads(body) if body else {}

        event = data.get("event", "")
        logger.info(f"Plex webhook received: event={event}")

        if event != "library.new":
            return {"status": "ignored", "reason": f"unhandled event: {event}"}

        settings = _load_settings()
        webhook = settings.get("webhook", {})
        if not webhook.get("enabled"):
            logger.info("Webhook ignored: disabled in settings")
            return {"status": "ignored", "reason": "webhook disabled"}

        metadata = data.get("Metadata", {})
        target_library = metadata.get("librarySectionTitle")
        if not target_library:
            logger.warning("Webhook ignored: no librarySectionTitle in metadata")
            return {"status": "ignored", "reason": "could not determine library from event"}

        # If libraries list is non-empty, only process the listed libraries
        allowed = webhook.get("libraries", [])
        if allowed and target_library not in allowed:
            logger.info(f"Webhook ignored: library {target_library!r} not in scope {allowed}")
            return {"status": "ignored", "reason": f"library {target_library!r} not in webhook scope"}

        rating_key = str(metadata.get("ratingKey", "")) or None
        item_title = metadata.get("title", "unknown")

        # Enqueue — worker processes items sequentially, no drops on bulk imports
        await webhook_queue.put((target_library, rating_key, item_title))
        queue_size = webhook_queue.qsize()
        logger.info(f"Webhook queued: {target_library} / {item_title} (key={rating_key}, queue={queue_size})")
        return {"status": "queued", "library": target_library, "item": item_title, "queue_size": queue_size}

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"status": "error", "reason": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
