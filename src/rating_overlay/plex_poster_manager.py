"""
Plex Poster Manager - Apply rating overlays to Plex library

Integrates all components: backup, rating fetch, overlay, upload
MIT License - Copyright (c) 2026 Kometizarr Contributors
"""

import logging
import time
from pathlib import Path
from typing import Optional, Dict, List, Any
from plexapi.server import PlexServer
from plexapi.library import LibrarySection

from .backup_manager import PosterBackupManager
from .rating_fetcher import RatingFetcher
from .badge_generator import BadgeGenerator
from .overlay_composer import OverlayComposer
from .multi_rating_badge import MultiRatingBadge
from ..utils.logger import ProgressTracker, print_header, print_subheader, print_summary

logger = logging.getLogger(__name__)


class PlexPosterManager:
    """Apply rating overlays to Plex posters with automatic backup"""

    def __init__(
        self,
        plex_url: str,
        plex_token: str,
        library_name: str,
        tmdb_api_key: str,
        omdb_api_key: Optional[str] = None,
        mdblist_api_key: Optional[str] = None,
        backup_dir: str = './data/kometizarr_backups',
        badge_style: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        rating_sources: Optional[Dict[str, bool]] = None
    ):
        """
        Initialize Plex poster manager

        Args:
            plex_url: Plex server URL
            plex_token: Plex authentication token
            library_name: Library name (e.g., 'Movies')
            tmdb_api_key: TMDB API key
            omdb_api_key: Optional OMDb API key
            backup_dir: Directory for poster backups
            badge_style: Optional dict with styling options (size, font, color, opacity)
            dry_run: If True, preview operations without applying
            rating_sources: Optional dict to control which ratings to show
                           e.g. {'tmdb': True, 'imdb': True, 'rt_critic': False, 'rt_audience': False}
                           If None, shows all available ratings
        """
        self.plex_url = plex_url
        self.plex_token = plex_token
        self.library_name = library_name
        self.dry_run = dry_run
        self.rating_sources = rating_sources or {}
        self.badge_style = badge_style or {}  # Store badge styling options

        # Connect to Plex
        self.server = PlexServer(plex_url, plex_token)
        self.library = self.server.library.section(library_name)

        # Initialize components
        self.backup_manager = PosterBackupManager(backup_dir)
        self.rating_fetcher = RatingFetcher(tmdb_api_key, omdb_api_key, mdblist_api_key)
        # BadgeGenerator is legacy (old unified badge), badge_style is now a dict for MultiRatingBadge
        self.badge_generator = BadgeGenerator(style='default')
        self.overlay_composer = OverlayComposer(self.badge_generator)
        self.multi_rating_badge = MultiRatingBadge()  # New multi-source badge (uses badge_style dict)

        # Temp directory for processing
        self.temp_dir = Path('/tmp/kometizarr_temp')
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Connected to Plex: {self.server.friendlyName}")
        logger.info(f"Library: {library_name} ({self.library.totalSize} items)")
        if dry_run:
            logger.info("DRY-RUN MODE: No changes will be applied")
        self._excluded_items = set()  # Populated externally from settings

    def _extract_tmdb_id(self, guids: list) -> Optional[int]:
        """Extract TMDB ID from Plex GUIDs"""
        for guid in guids:
            if 'tmdb://' in guid.id:
                return int(guid.id.split('tmdb://')[1])
        return None

    def _extract_imdb_id(self, guids: list) -> Optional[str]:
        """Extract IMDb ID from Plex GUIDs"""
        for guid in guids:
            if 'imdb://' in guid.id:
                return guid.id.split('imdb://')[1]
        return None

    def _extract_plex_ratings(self, movie) -> Dict[str, float]:
        """
        Extract ratings from Plex's own metadata

        Tries the modern `ratings` array first (Plex 1.30+), then falls back
        to legacy scalar fields (audienceRating, rating) which are more
        reliably populated.

        Returns:
            Dict with available ratings: {'tmdb': 7.5, 'imdb': 6.8, 'rt_critic': 30.0, 'rt_audience': 92.0}
        """
        plex_ratings = {}

        # Modern ratings array (Plex 1.30+, PlexAPI 4.15+)
        if hasattr(movie, 'ratings') and movie.ratings:
            for rating in movie.ratings:
                rating_type = rating.type
                rating_value = rating.value
                rating_image = rating.image if hasattr(rating, 'image') else ''

                # RT Critic (critic type with RT image)
                if rating_type == 'critic' and 'rottentomatoes' in rating_image:
                    plex_ratings['rt_critic'] = rating_value * 10  # Convert 0-10 to 0-100%

                # RT Audience (audience type with RT image)
                elif rating_type == 'audience' and 'rottentomatoes' in rating_image:
                    plex_ratings['rt_audience'] = rating_value * 10  # Convert 0-10 to 0-100%

                # IMDb (audience type with imdb image)
                elif rating_type == 'audience' and 'imdb' in rating_image:
                    plex_ratings['imdb'] = rating_value

                # TMDB (audience type with themoviedb image)
                elif rating_type == 'audience' and 'themoviedb' in rating_image:
                    plex_ratings['tmdb'] = rating_value

        # Fallback: legacy scalar fields (more reliably populated)
        if not plex_ratings:
            audience_rating = getattr(movie, 'audienceRating', None)
            audience_image = getattr(movie, 'audienceRatingImage', '') or ''
            critic_rating = getattr(movie, 'rating', None)
            critic_image = getattr(movie, 'ratingImage', '') or ''

            if audience_rating and audience_rating > 0:
                if 'imdb' in audience_image:
                    plex_ratings['imdb'] = audience_rating
                elif 'themoviedb' in audience_image:
                    plex_ratings['tmdb'] = audience_rating
                elif 'rottentomatoes' in audience_image:
                    plex_ratings['rt_audience'] = audience_rating * 10

            if critic_rating and critic_rating > 0:
                if 'rottentomatoes' in critic_image:
                    plex_ratings['rt_critic'] = critic_rating * 10
                elif 'themoviedb' in critic_image:
                    plex_ratings['tmdb'] = critic_rating

            if plex_ratings:
                logger.debug(f"  {movie.title}: Used legacy Plex fields (audienceRating={audience_rating}, rating={critic_rating})")

        return plex_ratings

    def _map_status_to_overlay(
        self,
        status_value: Optional[str],
        in_production: Optional[bool] = None,
        has_next_episode: Optional[bool] = None
    ) -> Optional[str]:
        """Map provider status text to overlay style key."""
        if not status_value or not status_value.strip():
            return None
        normalized = (status_value or '').strip().lower()

        # 1) Explicit cancelled states -> Cancelled overlay
        cancelled_tokens = ['cancel', 'cancelled', 'canceled']
        if any(token in normalized for token in cancelled_tokens):
            return 'cancelled'

        # 2) Explicit ended states -> Ended overlay
        ended_tokens = ['ended', 'end']
        if any(token in normalized for token in ended_tokens):
            return 'ended'

        # 2) Explicit renewed/returning states -> Renewed overlay
        renewed_tokens = ['renew', 'returning series', 'returning', 'coming back']
        if any(token in normalized for token in renewed_tokens):
            return 'renewed'

        # 3) Explicit current/live production states -> Current overlay
        current_tokens = [
            'in production', 'continuing', 'current', 'running',
            'airing', 'planned', 'pilot', 'production'
        ]
        if any(token in normalized for token in current_tokens):
            return 'current'

        # 4) Metadata hints when status text is weak/missing
        if has_next_episode:
            return 'renewed'
        if in_production is True:
            return 'current'

        return None

    def _resolve_item_status_overlay(
        self,
        item,
        tmdb_id: Optional[int] = None,
        tmdb_status: Optional[str] = None,
        imdb_id: Optional[str] = None
    ) -> Optional[str]:
        """Resolve status overlay for a single item when status_overlay is set to 'auto'."""
        if self.library.type != 'show':
            return None

        title = getattr(item, 'title', 'unknown')

        # 1) Try Plex metadata first
        plex_status = getattr(item, 'status', None) or getattr(item, 'showStatus', None)
        if plex_status:
            logger.debug(f"Status resolve '{title}': Plex status = '{plex_status}'")
        mapped = self._map_status_to_overlay(plex_status)
        if mapped:
            return mapped

        # 2) Use already-fetched TMDB status if available
        if tmdb_status:
            logger.debug(f"Status resolve '{title}': pre-fetched TMDB status = '{tmdb_status}'")
        mapped = self._map_status_to_overlay(tmdb_status)
        if mapped:
            return mapped

        # 3) Fallback TMDB lookup for status only
        if tmdb_id:
            rating_data = self.rating_fetcher.fetch_tmdb_rating(tmdb_id, media_type='tv')
            if rating_data:
                fetched_status = rating_data.get('status')
                in_prod = rating_data.get('in_production')
                next_ep = bool(rating_data.get('next_episode_to_air'))
                logger.debug(f"Status resolve '{title}': TMDB id={tmdb_id} status='{fetched_status}' in_production={in_prod} next_ep={next_ep}")
                mapped = self._map_status_to_overlay(
                    fetched_status,
                    in_production=in_prod,
                    has_next_episode=next_ep
                )
                if mapped:
                    return mapped

        # 4) Resolve TMDB TV status via IMDb ID (common when Plex has IMDb GUID but no TMDB GUID)
        if imdb_id:
            imdb_tmdb_data = self.rating_fetcher.fetch_tmdb_tv_status_by_imdb_id(imdb_id)
            if imdb_tmdb_data:
                fetched_status = imdb_tmdb_data.get('status')
                in_prod = imdb_tmdb_data.get('in_production')
                next_ep = bool(imdb_tmdb_data.get('next_episode_to_air'))
                logger.debug(f"Status resolve '{title}': TMDB-via-IMDb({imdb_id}) status='{fetched_status}' in_production={in_prod} next_ep={next_ep}")
                mapped = self._map_status_to_overlay(
                    fetched_status,
                    in_production=in_prod,
                    has_next_episode=next_ep
                )
                if mapped:
                    return mapped

        # 5) Last fallback: TMDB title search
        year = getattr(item, 'year', None)
        title_tmdb_data = self.rating_fetcher.fetch_tmdb_tv_status_by_title(title, year=year)
        if title_tmdb_data:
            fetched_status = title_tmdb_data.get('status')
            in_prod = title_tmdb_data.get('in_production')
            next_ep = bool(title_tmdb_data.get('next_episode_to_air'))
            logger.debug(f"Status resolve '{title}': TMDB-title-search status='{fetched_status}' in_production={in_prod} next_ep={next_ep}")
            mapped = self._map_status_to_overlay(
                fetched_status,
                in_production=in_prod,
                has_next_episode=bool(title_tmdb_data.get('next_episode_to_air'))
            )
            if mapped:
                return mapped

        logger.info(f"Auto status unresolved for '{title}' (tmdb_id={tmdb_id}, imdb_id={imdb_id})")

        return None

    def _build_effective_badge_style(self, item, tmdb_id: Optional[int] = None, tmdb_status: Optional[str] = None) -> Dict[str, Any]:
        """Build final badge style for an item, resolving auto status overlay if configured."""
        effective_style = dict(self.badge_style or {})
        selected_status = str(effective_style.get('status_overlay', 'none')).strip().lower()

        # Status overlays only apply to TV shows
        if self.library.type != 'show' and selected_status != 'none':
            effective_style['status_overlay'] = 'none'
            return effective_style

        # Check per-show status override first
        status_overrides = effective_style.get('status_overrides', {}).get(self.library_name, {})
        safe_title = "".join(c for c in item.title if c.isalnum() or c in (' ', '-', '_')).strip()
        if safe_title in status_overrides:
            effective_style['status_overlay'] = status_overrides[safe_title]
            return effective_style

        if selected_status != 'auto':
            return effective_style

        resolved_status = self._resolve_item_status_overlay(item, tmdb_id=tmdb_id, tmdb_status=tmdb_status, imdb_id=self._extract_imdb_id(item.guids))
        effective_style['status_overlay'] = resolved_status or 'none'
        return effective_style

    def process_movie(
        self,
        movie,
        position: str = 'northwest',
        force: bool = False,
        badge_positions: Optional[Dict[str, Dict[str, float]]] = None
    ) -> Optional[bool]:
        """
        Process a single movie: backup, overlay, upload

        Args:
            movie: PlexAPI movie object
            position: Badge position ('northeast', 'northwest', etc.) - legacy unified mode
            force: Force reprocessing even if already has overlay
            badge_positions: Optional dict for individual badge positions
                           {'tmdb': {'x': 5, 'y': 5}, 'imdb': {'x': 20, 'y': 5}, ...}

        Returns:
            True if successfully processed
            None if skipped (already has overlay)
            False if failed
        """
        try:
            # Ensure full item data is loaded (ratings, guids require detail fetch)
            for attempt in range(2):
                try:
                    movie.reload()
                    break
                except Exception as e:
                    if attempt == 0:
                        import time
                        time.sleep(1)
                    else:
                        logger.warning(f"⚠️  {movie.title}: Plex reload failed after retry ({e}), using cached data")

            # Extract IDs - TMDB ID is optional (many TV shows don't have it)
            tmdb_id = self._extract_tmdb_id(movie.guids)
            imdb_id = self._extract_imdb_id(movie.guids)
            tmdb_status = None

            # Need at least one ID to proceed
            if not tmdb_id and not imdb_id:
                logger.warning(f"⚠️  {movie.title}: No TMDB or IMDb ID found")
                return False

            # Check exclude list
            if hasattr(self, '_excluded_items') and self._excluded_items:
                safe_title = "".join(c for c in movie.title if c.isalnum() or c in (' ', '-', '_')).strip()
                if safe_title in self._excluded_items:
                    logger.debug(f"⏭️  {movie.title}: Excluded by user, skipping")
                    return None

            # Skip if overlay already applied (unless force=True)
            if not force and self.backup_manager.has_overlay(self.library_name, movie.title, rating_key=movie.ratingKey):
                logger.debug(f"⏭️  {movie.title}: Already has overlay, skipping")
                return None  # Return None to indicate skip (not success or failure)

            # PRIORITY 1: Try to get ALL ratings from Plex's own metadata FIRST (fastest, most reliable)
            # This works for both movies AND TV shows and has ~100% coverage
            plex_ratings = self._extract_plex_ratings(movie)
            if not plex_ratings:
                logger.debug(
                    f"  {movie.title}: No Plex embedded ratings "
                    f"(ratings attr={'yes' if hasattr(movie, 'ratings') and movie.ratings else 'no'}, "
                    f"audienceRating={getattr(movie, 'audienceRating', None)}, "
                    f"audienceRatingImage={getattr(movie, 'audienceRatingImage', None)}, "
                    f"rating={getattr(movie, 'rating', None)}, "
                    f"ratingImage={getattr(movie, 'ratingImage', None)})"
                )

            # Build ratings dict - start with what Plex has
            ratings = {}

            # Use Plex's TMDB rating if available
            if 'tmdb' in plex_ratings:
                ratings['tmdb'] = plex_ratings['tmdb']

            # Always fetch TMDB data when we have a TMDB ID (needed for status resolution)
            if tmdb_id:
                media_type = 'tv' if self.library.type == 'show' else 'movie'
                rating_data = self.rating_fetcher.fetch_tmdb_rating(tmdb_id, media_type=media_type)
                if rating_data:
                    tmdb_status = rating_data.get('status')

                if rating_data and 'tmdb' not in ratings:
                    tmdb_rating = rating_data.get('rating', 0)
                    if tmdb_rating > 0:
                        ratings['tmdb'] = tmdb_rating
                    elif rating_data.get('vote_count', 0) == 0:
                        logger.debug(f"  {movie.title}: TMDB has no votes yet, skipping TMDB rating")
                # Don't fail here - continue to check other rating sources

            # Use Plex's IMDb rating if available
            if 'imdb' in plex_ratings:
                ratings['imdb'] = plex_ratings['imdb']

            # Use Plex's RT scores if available
            if 'rt_critic' in plex_ratings:
                ratings['rt_critic'] = plex_ratings['rt_critic']
            if 'rt_audience' in plex_ratings:
                ratings['rt_audience'] = plex_ratings['rt_audience']

            # PRIORITY 2: Fall back to API calls for missing ratings (already extracted imdb_id above)
            if imdb_id:
                # Get IMDb rating from OMDb if not already from Plex
                if 'imdb' not in ratings:
                    imdb_data = self.rating_fetcher.fetch_omdb_rating(imdb_id)
                    if imdb_data and imdb_data.get('imdb_rating'):
                        try:
                            ratings['imdb'] = float(imdb_data['imdb_rating'])
                        except:
                            pass

                # Get all available ratings from MDBList (IMDb, TMDB, RT critic, RT audience)
                mdb_data = self.rating_fetcher.fetch_mdblist_rating(imdb_id)
                if mdb_data:
                    for key in ('imdb', 'tmdb', 'rt_critic', 'rt_audience'):
                        if key not in ratings and mdb_data.get(key):
                            ratings[key] = mdb_data[key]

            # Filter ratings based on user preferences (if specified)
            if self.rating_sources:
                ratings = {
                    k: v for k, v in ratings.items()
                    if self.rating_sources.get(k, True)  # Default to True if not specified
                }

            # Remove zero-value ratings (no votes yet = nothing meaningful to display)
            ratings = {k: v for k, v in ratings.items() if v and v > 0}

            # Check if we have ANY ratings to display
            if not ratings:
                selected_status = str((self.badge_style or {}).get('status_overlay', 'none')).strip().lower()
                if selected_status == 'none':
                    logger.warning(
                        f"⚠️  {movie.title}: No ratings found "
                        f"(tmdb_id={tmdb_id}, imdb_id={imdb_id}, "
                        f"plex_ratings={plex_ratings}, "
                        f"enabled_sources={self.rating_sources})"
                    )
                    return False
                logger.info(f"⚠️  {movie.title}: No ratings but status overlay enabled, proceeding")

            logger.info(f"Processing: {movie.title} (Ratings: {ratings})")

            if self.dry_run:
                logger.info(f"[DRY-RUN] Would apply multi-rating overlay to '{movie.title}': {ratings}")
                return True

            # Get poster URL
            poster_url = movie.posterUrl
            if not poster_url:
                logger.warning(f"⚠️  {movie.title}: No poster URL")
                return False

            # Backup original poster
            metadata = {
                'rating_key': movie.ratingKey,
                'tmdb_id': tmdb_id,
                'imdb_id': imdb_id,
                'title': movie.title,
                'year': movie.year,
                'ratings': ratings
            }

            # Get or create backup (never re-download if backup exists)
            # When force=True, we just use existing backup to apply fresh overlay
            original_path = self.backup_manager.backup_poster(
                library_name=self.library_name,
                item_title=movie.title,
                poster_url=poster_url,
                item_metadata=metadata,
                plex_token=self.plex_token,
                force=False  # Never re-download - use existing backup
            )

            if not original_path:
                logger.error(f"✗ {movie.title}: Failed to backup poster")
                return False

            # Apply multi-rating overlay
            overlay_path = self.temp_dir / f"{movie.ratingKey}_overlay.jpg"
            effective_badge_style = self._build_effective_badge_style(movie, tmdb_id=tmdb_id, tmdb_status=tmdb_status)
            if str((self.badge_style or {}).get('status_overlay', 'none')).strip().lower() == 'auto':
                logger.info(f"Auto status for '{movie.title}': {effective_badge_style.get('status_overlay', 'none')}")
            self.multi_rating_badge.apply_to_poster(
                poster_path=str(original_path),
                ratings=ratings,
                output_path=str(overlay_path),
                position=position,
                badge_style=effective_badge_style,  # Pass custom styling options
                badge_positions=badge_positions  # Pass individual badge positions if provided
            )

            # Save overlay version to backup
            self.backup_manager.save_overlay_poster(
                library_name=self.library_name,
                item_title=movie.title,
                overlay_image_path=str(overlay_path)
            )

            # Upload to Plex
            movie.uploadPoster(filepath=str(overlay_path))
            rating_str = ', '.join([f'{k.upper()}: {v:.1f}' for k, v in ratings.items()])
            logger.info(f"✓ {movie.title}: Multi-rating overlay applied ({rating_str})")

            # Cleanup temp file
            overlay_path.unlink()

            return True

        except Exception as e:
            logger.error(f"✗ {movie.title}: Error - {e}")
            return False

    def process_library(
        self,
        limit: Optional[int] = None,
        position: str = 'northwest',
        force: bool = False,
        rate_limit: float = 0.3
    ) -> Dict[str, int]:
        """
        Process entire library with rating overlays

        Args:
            limit: Max number of movies to process (None = all)
            position: Badge position
            force: Force reprocessing
            rate_limit: Delay between requests (seconds)

        Returns:
            Dict with statistics
        """
        all_movies = self.library.all()
        total = len(all_movies)

        if limit:
            all_movies = all_movies[:limit]
            print_header(f"Processing {limit} of {total} Movies")
        else:
            print_header(f"Processing All {total} Movies")

        # Initialize progress tracker
        progress = ProgressTracker(len(all_movies), "Applying rating overlays")
        start_time = time.time()

        print(f"Library: {self.library_name}")
        print(f"Backup Dir: {self.backup_manager.backup_dir}")
        print(f"Position: {position}")
        print(f"Force Reprocess: {force}")
        print()

        for i, movie in enumerate(all_movies, 1):
            # Show progress
            print_subheader(f"{progress.get_progress_str()} | {movie.title}")

            result = self.process_movie(movie, position=position, force=force)

            # Update progress based on result
            if result is None:
                # None = skipped (already has overlay)
                progress.update(skipped=True)
            elif result:
                # True = success
                progress.update(success=True)
            else:
                # False = failed
                progress.update(success=False)

            # Show current stats
            print(f"  {progress.get_stats_str()}")

            # Rate limiting (respect TMDB limits)
            time.sleep(rate_limit)

        elapsed = time.time() - start_time

        # Final summary
        stats = {
            'Total Movies': len(all_movies),
            'Successfully Processed': progress.success,
            'Skipped (Already Done)': progress.skipped,
            'Failed': progress.failed,
            'Total Time': f"{elapsed:.1f}s ({elapsed/60:.1f}min)",
            'Average Speed': f"{elapsed/len(all_movies):.2f}s per movie",
            'Processing Rate': f"{len(all_movies)/elapsed:.2f} movies/sec"
        }

        print_summary(stats)

        return {
            'total': len(all_movies),
            'success': progress.success,
            'skipped': progress.skipped,
            'failed': progress.failed,
            'elapsed': elapsed
        }

    def restore_movie(self, movie_title: str) -> bool:
        """
        Restore original poster for a movie

        Args:
            movie_title: Movie title

        Returns:
            True if restored
        """
        # Find movie in library
        try:
            movie = self.library.get(movie_title)
        except Exception as e:
            logger.error(f"Movie not found: {movie_title}")
            return False

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would restore original poster for '{movie_title}'")
            return True

        return self.backup_manager.restore_original(
            library_name=self.library_name,
            item_title=movie_title,
            plex_item=movie
        )

    def restore_library(self) -> int:
        """
        Restore all original posters in library

        Returns:
            Number of posters restored
        """
        backups = self.backup_manager.list_backups(library_name=self.library_name)
        restored_count = 0

        logger.info(f"Restoring {len(backups)} original posters...")

        for backup in backups:
            if self.restore_movie(backup['title']):
                restored_count += 1

        logger.info(f"✓ Restored {restored_count}/{len(backups)} posters")
        return restored_count

    def list_backups(self) -> List[Dict]:
        """List all backed up posters"""
        return self.backup_manager.list_backups(library_name=self.library_name)


def main():
    """Example usage"""
    import json
    import argparse
    from ..utils.logger import setup_logger

    # Parse arguments
    parser = argparse.ArgumentParser(description='Kometizarr Plex Poster Manager')
    parser.add_argument('--config', default='config.json', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Preview without applying')
    parser.add_argument('--limit', type=int, help='Limit number of movies to process')
    parser.add_argument('--force', action='store_true', help='Force reprocess all movies')
    parser.add_argument('--restore', action='store_true', help='Restore original posters')
    parser.add_argument('--restore-movie', type=str, help='Restore specific movie')
    args = parser.parse_args()

    # Load config
    with open(args.config) as f:
        config = json.load(f)

    # Setup better logging
    setup_logger('kometizarr', level=logging.INFO)

    # Initialize manager
    manager = PlexPosterManager(
        plex_url=config['plex']['url'],
        plex_token=config['plex']['token'],
        library_name=config['plex']['library'],
        tmdb_api_key=config['apis']['tmdb']['api_key'],
        omdb_api_key=config['apis'].get('omdb', {}).get('api_key'),
        mdblist_api_key=config['apis'].get('mdblist', {}).get('api_key'),
        backup_dir=config['output']['directory'],
        badge_style=config['rating_overlay']['badge'].get('style', 'default'),
        dry_run=args.dry_run,
        rating_sources=config['rating_overlay'].get('sources', None)
    )

    # Restore mode
    if args.restore:
        manager.restore_library()
        return

    if args.restore_movie:
        manager.restore_movie(args.restore_movie)
        return

    # Process library
    if config['rating_overlay']['enabled']:
        position = config['rating_overlay']['badge'].get('position', 'northeast')

        manager.process_library(
            limit=args.limit,
            position=position,
            force=args.force
        )


if __name__ == '__main__':
    main()
