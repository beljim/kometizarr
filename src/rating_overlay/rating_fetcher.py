"""
Rating Fetcher - Fetch ratings from TMDB, TVDB, and OMDb APIs

Based on prototype_rating_overlay.py
MIT License - Copyright (c) 2026 Kometizarr Contributors
"""

import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RatingFetcher:
    """Fetch ratings from multiple sources"""

    TMDB_BASE_URL = "https://api.themoviedb.org/3"
    OMDB_BASE_URL = "http://www.omdbapi.com/"
    MDBLIST_BASE_URL = "https://mdblist.com/api"
    REQUEST_TIMEOUT = 15

    def __init__(self, tmdb_api_key: str, omdb_api_key: Optional[str] = None, mdblist_api_key: Optional[str] = None):
        """
        Initialize rating fetcher

        Args:
            tmdb_api_key: TMDB API key or v4 Read Access Token (required)
            omdb_api_key: OMDb API key (optional, for IMDb/RT ratings)
            mdblist_api_key: MDBList API key (optional, for RT audience scores)
        """
        self.omdb_api_key = omdb_api_key
        self.mdblist_api_key = mdblist_api_key

        # Detect placeholder keys that aren't real
        _placeholders = {'', 'YOUR_OMDB_KEY', 'YOUR_OMDB_API_KEY', 'YOUR_OMDB_API_KEY_HERE'}
        if self.omdb_api_key and self.omdb_api_key.strip().upper() in {p.upper() for p in _placeholders}:
            self.omdb_api_key = None
        _mdb_placeholders = {'', 'YOUR_MDBLIST_KEY', 'YOUR_MDBLIST_API_KEY', 'YOUR_MDBLIST_API_KEY_HERE'}
        if self.mdblist_api_key and self.mdblist_api_key.strip().upper() in {p.upper() for p in _mdb_placeholders}:
            self.mdblist_api_key = None

        # Create a session with automatic retry for transient failures
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Auto-detect whether the user supplied a v3 API key or a v4 Bearer token
        if tmdb_api_key and tmdb_api_key.startswith("eyJ"):
            # JWT / v4 Read Access Token → use Authorization header
            self.tmdb_api_key = None
            self._tmdb_headers = {
                "Authorization": f"Bearer {tmdb_api_key}",
                "accept": "application/json",
            }
        else:
            self.tmdb_api_key = tmdb_api_key
            self._tmdb_headers = {}

    # ── helper for all TMDB requests ──────────────────────────────
    def _tmdb_get(self, path: str, extra_params: Optional[Dict] = None) -> requests.Response:
        """Make a GET to TMDB using whichever auth method was configured."""
        url = f"{self.TMDB_BASE_URL}/{path}"
        params = dict(extra_params or {})
        if self.tmdb_api_key:
            params["api_key"] = self.tmdb_api_key
        return self.session.get(url, params=params, headers=self._tmdb_headers, timeout=self.REQUEST_TIMEOUT)

    def fetch_tmdb_rating(self, tmdb_id: int, media_type: str = 'movie') -> Optional[Dict]:
        """
        Fetch TMDB rating for a movie or TV show

        Args:
            tmdb_id: TMDB ID
            media_type: 'movie' or 'tv'

        Returns:
            Dict with rating, vote_count, and title, or None if error
        """
        try:
            response = self._tmdb_get(f"{media_type}/{tmdb_id}")
            response.raise_for_status()
            data = response.json()

            rating = data.get('vote_average', 0)
            vote_count = data.get('vote_count', 0)
            title = data.get('title') if media_type == 'movie' else data.get('name')

            return {
                'rating': rating,
                'vote_count': vote_count,
                'title': title,
                'status': data.get('status'),
                'in_production': data.get('in_production'),
                'next_episode_to_air': data.get('next_episode_to_air'),
                'source': 'tmdb'
            }
        except Exception as e:
            logger.warning(f"TMDB rating fetch failed for {media_type}/{tmdb_id}: {e}")
            return None

    def fetch_tmdb_episode_rating(self, tmdb_id: int, season: int, episode: int) -> Optional[Dict]:
        """
        Fetch TMDB rating for a specific TV episode

        Args:
            tmdb_id: TMDB TV show ID
            season: Season number
            episode: Episode number

        Returns:
            Dict with rating and vote_count, or None if error
        """
        try:
            response = self._tmdb_get(f"tv/{tmdb_id}/season/{season}/episode/{episode}")
            response.raise_for_status()
            data = response.json()

            return {
                'rating': data.get('vote_average', 0),
                'vote_count': data.get('vote_count', 0),
                'episode_name': data.get('name'),
                'source': 'tmdb'
            }
        except Exception as e:
            logger.warning(f"TMDB episode rating fetch failed: {e}")
            return None

    def fetch_omdb_rating(self, imdb_id: str) -> Optional[Dict]:
        """
        Fetch IMDb and Rotten Tomatoes ratings from OMDb

        Args:
            imdb_id: IMDb ID (e.g., 'tt0111161')

        Returns:
            Dict with imdb_rating, rt_audience, rt_critic, or None if error
        """
        if not self.omdb_api_key:
            logger.debug("OMDb API key not configured")
            return None

        url = f"{self.OMDB_BASE_URL}?i={imdb_id}&apikey={self.omdb_api_key}"

        try:
            response = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get('Response') == 'False':
                logger.debug(f"OMDb returned no data for {imdb_id}: {data.get('Error')}")
                return None

            # Parse ratings
            result = {
                'imdb_rating': data.get('imdbRating'),
                'imdb_votes': data.get('imdbVotes'),
                'source': 'omdb'
            }

            # Parse RT ratings from Ratings array
            for rating in data.get('Ratings', []):
                if rating['Source'] == 'Rotten Tomatoes':
                    result['rt_score'] = rating['Value']  # e.g., "95%"
                elif rating['Source'] == 'Metacritic':
                    result['metacritic'] = rating['Value']  # e.g., "80/100"

            return result
        except Exception as e:
            logger.warning(f"OMDb rating fetch failed for {imdb_id}: {e}")
            return None

    def fetch_mdblist_rating(self, imdb_id: str) -> Optional[Dict]:
        """
        Fetch ratings from MDBList (IMDb, TMDB, RT critic & audience)

        Args:
            imdb_id: IMDb ID (e.g., 'tt0111161')

        Returns:
            Dict with available ratings, or None if error
        """
        if not self.mdblist_api_key:
            logger.debug("MDBList API key not configured")
            return None

        url = f"{self.MDBLIST_BASE_URL}/?apikey={self.mdblist_api_key}&i={imdb_id}"

        try:
            response = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            result = {}

            # MDBList returns ratings in format like: ratings[0].source = "imdb", ratings[0].value = 75
            ratings_data = data.get('ratings', [])

            for rating in ratings_data:
                source = rating.get('source', '').lower()
                value = rating.get('value')

                if source == 'imdb' and value:
                    # MDBList IMDb score is 0-100, convert to 0-10 scale
                    result['imdb'] = round(float(value) / 10, 1)
                elif source == 'tmdb' and value:
                    # MDBList TMDB score is 0-100, convert to 0-10 scale
                    result['tmdb'] = round(float(value) / 10, 1)
                elif source == 'tomatoes' and value:
                    result['rt_critic'] = float(value)
                elif source == 'tomatoesaudience' and value:
                    result['rt_audience'] = float(value)

            return result if result else None

        except Exception as e:
            logger.warning(f"MDBList rating fetch failed for {imdb_id}: {e}")
            return None

    def fetch_tmdb_tv_status_by_imdb_id(self, imdb_id: str) -> Optional[Dict]:
        """Resolve TMDB TV status by IMDb ID via TMDB /find endpoint."""
        if not imdb_id:
            return None

        try:
            response = self._tmdb_get(f"find/{imdb_id}", {"external_source": "imdb_id"})
            response.raise_for_status()
            data = response.json()
            tv_results = data.get('tv_results', [])
            if not tv_results:
                return None

            tmdb_id = tv_results[0].get('id')
            if not tmdb_id:
                return None

            details = self.fetch_tmdb_rating(tmdb_id, media_type='tv')
            if not details:
                return None

            details['tmdb_id'] = tmdb_id
            return details
        except Exception as e:
            logger.warning(f"TMDB TV status by IMDb ID failed for {imdb_id}: {e}")
            return None

    def fetch_tmdb_tv_status_by_title(self, title: Optional[str], year: Optional[int] = None) -> Optional[Dict]:
        """Resolve TMDB TV status by title search as a last fallback."""
        if not title:
            return None

        params = {
            'query': title,
            'include_adult': 'false',
        }
        if year:
            params['first_air_date_year'] = str(year)

        try:
            response = self._tmdb_get("search/tv", params)
            response.raise_for_status()
            data = response.json()
            results = data.get('results', [])
            if not results:
                return None

            tmdb_id = results[0].get('id')
            if not tmdb_id:
                return None

            details = self.fetch_tmdb_rating(tmdb_id, media_type='tv')
            if not details:
                return None

            details['tmdb_id'] = tmdb_id
            return details
        except Exception as e:
            logger.warning(f"TMDB TV status by title failed for '{title}': {e}")
            return None
