"""
TMDB Helper - Fetch movies by keyword, collection, or other TMDB criteria

MIT License - Copyright (c) 2026 Kometizarr Contributors
"""

import requests
from typing import List, Dict, Optional


class TMDBHelper:
    """Helper for TMDB API searches"""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str):
        """
        Initialize TMDB helper

        Args:
            api_key: TMDB API key or v4 Read Access Token
        """
        # Auto-detect v3 key vs v4 Bearer token
        if api_key and api_key.startswith("eyJ"):
            self.api_key = None
            self._headers = {
                "Authorization": f"Bearer {api_key}",
                "accept": "application/json",
            }
        else:
            self.api_key = api_key
            self._headers = {}

    def _get(self, path: str, extra_params: Optional[Dict] = None) -> requests.Response:
        """Make a GET to TMDB with the correct auth method."""
        url = f"{self.BASE_URL}/{path}"
        params = dict(extra_params or {})
        if self.api_key:
            params["api_key"] = self.api_key
        return requests.get(url, params=params, headers=self._headers)

    def get_movies_by_keyword(self, keyword_id: int, limit: int = 500) -> List[int]:
        """
        Get TMDB movie IDs that match a keyword

        Args:
            keyword_id: TMDB keyword ID (e.g., 12377 for "zombie")
            limit: Maximum number of results

        Returns:
            List of TMDB movie IDs
        """
        movie_ids = []
        page = 1

        while len(movie_ids) < limit:
            params = {
                "with_keywords": keyword_id,
                "page": page,
                "sort_by": "popularity.desc"
            }

            try:
                response = self._get("discover/movie", params)
                response.raise_for_status()
                data = response.json()

                results = data.get('results', [])
                if not results:
                    break

                movie_ids.extend([movie['id'] for movie in results])

                # Check if there are more pages
                if page >= data.get('total_pages', 1):
                    break

                page += 1

            except Exception as e:
                print(f"Error fetching keyword {keyword_id} page {page}: {e}")
                break

        return movie_ids[:limit]

    def get_tv_by_keyword(self, keyword_id: int, limit: int = 500) -> List[int]:
        """
        Get TMDB TV show IDs that match a keyword

        Args:
            keyword_id: TMDB keyword ID (e.g., 12377 for "zombie")
            limit: Maximum number of results

        Returns:
            List of TMDB TV show IDs
        """
        tv_ids = []
        page = 1

        while len(tv_ids) < limit:
            params = {
                "with_keywords": keyword_id,
                "page": page,
                "sort_by": "popularity.desc"
            }

            try:
                response = self._get("discover/tv", params)
                response.raise_for_status()
                data = response.json()

                results = data.get('results', [])
                if not results:
                    break

                tv_ids.extend([show['id'] for show in results])

                # Check if there are more pages
                if page >= data.get('total_pages', 1):
                    break

                page += 1

            except Exception as e:
                print(f"Error fetching TV keyword {keyword_id} page {page}: {e}")
                break

        return tv_ids[:limit]

    def get_movies_in_collection(self, collection_id: int) -> List[int]:
        """
        Get TMDB movie IDs in a collection

        Args:
            collection_id: TMDB collection ID (e.g., 2961 for South Park)

        Returns:
            List of TMDB movie IDs
        """
        try:
            response = self._get(f"collection/{collection_id}")
            response.raise_for_status()
            data = response.json()

            parts = data.get('parts', [])
            return [movie['id'] for movie in parts]

        except Exception as e:
            print(f"Error fetching collection {collection_id}: {e}")
            return []

    def search_keyword(self, keyword_name: str) -> Optional[int]:
        """
        Search for a keyword by name and return its ID

        Args:
            keyword_name: Keyword to search for (e.g., "zombie")

        Returns:
            Keyword ID or None if not found
        """
        params = {
            "query": keyword_name
        }

        try:
            response = self._get("search/keyword", params)
            response.raise_for_status()
            data = response.json()

            results = data.get('results', [])
            if results:
                return results[0]['id']

        except Exception as e:
            print(f"Error searching keyword '{keyword_name}': {e}")

        return None
