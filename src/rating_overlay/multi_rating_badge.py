"""
Multi-Rating Badge Generator - Create Kometa-style rating overlays with multiple sources

Supports TMDB, IMDb, and Rotten Tomatoes ratings with logos
MIT License - Copyright (c) 2026 Kometizarr Contributors
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Tuple, Dict, Optional, List, Any
from pathlib import Path


# ── Badge Templates ──────────────────────────────────────────────────────────
# Each template defines the badge shape, background style, and text rendering.
# Templates are referenced by badge_style.get('badge_template', 'default').

BADGE_TEMPLATES = {
    'default': {
        'label': 'Classic',
        'description': 'Rounded rectangle with semi-transparent background',
        'corner_radius_pct': 0.10,      # % of badge width
        'aspect_ratio': 1.4,            # height = width * aspect_ratio
        'logo_section_pct': 0.60,       # top 60% for logo
        'gradient': False,
        'border': False,
        'shadow': True,
    },
    'minimal': {
        'label': 'Minimal',
        'description': 'No background, logo + number with strong text shadow',
        'corner_radius_pct': 0,
        'aspect_ratio': 1.4,
        'logo_section_pct': 0.60,
        'gradient': False,
        'border': False,
        'shadow': True,
        'no_background': True,
    },
    'pill': {
        'label': 'Pill',
        'description': 'Fully rounded pill shape',
        'corner_radius_pct': 0.50,      # 50% = full pill
        'aspect_ratio': 1.4,
        'logo_section_pct': 0.60,
        'gradient': False,
        'border': False,
        'shadow': True,
    },
    'bordered': {
        'label': 'Bordered',
        'description': 'Rounded rectangle with colored border',
        'corner_radius_pct': 0.10,
        'aspect_ratio': 1.4,
        'logo_section_pct': 0.60,
        'gradient': False,
        'border': True,
        'border_width_pct': 0.04,       # % of badge width
        'shadow': True,
    },
    'gradient': {
        'label': 'Gradient',
        'description': 'Dark gradient background from top to bottom',
        'corner_radius_pct': 0.10,
        'aspect_ratio': 1.4,
        'logo_section_pct': 0.60,
        'gradient': True,
        'gradient_top_opacity': 200,
        'gradient_bottom_opacity': 80,
        'border': False,
        'shadow': True,
    },
    'square': {
        'label': 'Square',
        'description': 'Sharp corners square badge',
        'corner_radius_pct': 0.0,
        'aspect_ratio': 1.4,
        'logo_section_pct': 0.60,
        'gradient': False,
        'border': False,
        'shadow': True,
    },
}


class MultiRatingBadge:
    """Generate rating badges with multiple sources (TMDB, IMDb, RT)"""

    # Font family to file path mapping
    FONT_PATHS = {
        'DejaVu Sans Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        'DejaVu Sans': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'DejaVu Sans Bold Oblique': '/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf',
        'DejaVu Sans Oblique': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
        'DejaVu Serif Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
        'DejaVu Serif': '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
        'DejaVu Serif Bold Italic': '/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf',
        'DejaVu Serif Italic': '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf',
        'DejaVu Sans Mono Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
        'DejaVu Sans Mono': '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        'DejaVu Sans Mono Oblique': '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf',
    }

    STATUS_STYLES = {
        'cancelled': {'label': 'CANCELLED', 'color': (220, 38, 38, 180)},
        'ended': {'label': 'ENDED', 'color': (249, 115, 22, 255)},
        'renewed': {'label': 'RENEWED', 'color': (34, 197, 94, 180)},
        'current': {'label': 'CURRENT', 'color': (59, 130, 246, 255)},
    }

    def __init__(self, assets_dir: str = None):
        """
        Initialize multi-rating badge generator

        Args:
            assets_dir: Path to assets directory with logos
        """
        if assets_dir:
            self.assets_dir = Path(assets_dir)
        else:
            # Try Docker mount path first, fall back to local development path
            docker_path = Path('/app/kometizarr/assets/logos')
            if docker_path.exists():
                self.assets_dir = docker_path
            else:
                # Local development - relative to this file
                self.assets_dir = Path(__file__).parent.parent.parent / 'assets' / 'logos'

        # Load logos
        self.logos = self._load_logos()

    def _load_logos(self) -> Dict[str, Optional[Image.Image]]:
        """Load rating source logos"""
        logos = {}

        logo_files = {
            'tmdb': 'tmdb.png',
            'imdb': 'imdb.png',
            'rt_fresh': 'rt_fresh.png',
            'rt_rotten': 'rt_rotten.png',
            'rt_audience_fresh': 'rt_audience_fresh.png',
            'rt_audience_rotten': 'rt_audience_rotten.png'
        }

        for source, filename in logo_files.items():
            logo_path = self.assets_dir / filename
            if logo_path.exists():
                try:
                    logos[source] = Image.open(logo_path).convert('RGBA')
                except Exception as e:
                    print(f"Failed to load {source} logo: {e}")
                    logos[source] = None
            else:
                logos[source] = None

        return logos

    def _draw_text_with_shadow(
        self,
        draw: ImageDraw.Draw,
        position: Tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        color: Tuple[int, int, int, int],
        shadow_offset: int = 6,
        anchor: str = "lm",
        stroke_width: int = None
    ):
        """Draw text with drop shadow for better visibility"""
        x, y = position

        # Auto-scale stroke width if not provided
        if stroke_width is None:
            stroke_width = max(2, shadow_offset // 2)

        # Draw shadow (slightly offset, darker)
        draw.text(
            (x + shadow_offset, y + shadow_offset),
            text,
            font=font,
            fill=(0, 0, 0, 200),  # Dark shadow
            anchor=anchor,
            stroke_width=stroke_width + 1,
            stroke_fill=(0, 0, 0, 255)
        )

        # Draw main text
        draw.text(
            (x, y),
            text,
            font=font,
            fill=color,
            anchor=anchor,
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0, 200)  # Outline for extra visibility
        )

    def create_multi_rating_badge(
        self,
        ratings: Dict[str, float],
        poster_size: Tuple[int, int],
        position: str = 'northeast',
        badge_style: Optional[Dict[str, Any]] = None
    ) -> Image.Image:
        """
        Create a badge with multiple rating sources

        Args:
            ratings: Dict like {'tmdb': 7.2, 'imdb': 7.5, 'rt': 85}
            poster_size: (width, height) of poster
            position: Badge position
            badge_style: Optional styling options (badge_width_percent, font_size_multiplier, rating_color, background_opacity)

        Returns:
            PIL Image with transparent background
        """
        poster_width, poster_height = poster_size

        # Apply custom styling or use defaults
        style = badge_style or {}
        badge_width_percent = style.get('badge_width_percent', 35) / 100  # Convert percentage to decimal
        font_multiplier = style.get('font_size_multiplier', 1.0)
        rating_color_hex = style.get('rating_color', '#FFD700')  # Gold
        background_opacity = style.get('background_opacity', 128)

        # Convert hex color to RGB tuple
        rating_color = tuple(int(rating_color_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (255,)

        # Badge size scales with poster width (customizable)
        badge_width = int(poster_width * badge_width_percent)

        # Calculate height based on number of ratings
        # Scale row height proportionally with badge width
        num_ratings = len(ratings)
        row_height = int(badge_width * 0.27)  # Proportional to width
        padding = int(badge_width * 0.03)
        badge_height = (num_ratings * row_height) + (padding * 2)

        # Create badge with transparent background
        badge = Image.new('RGBA', (badge_width, badge_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)

        # Draw semi-transparent black rounded rectangle background
        corner_radius = int(badge_width * 0.05)  # 5% of badge width
        draw.rounded_rectangle(
            [(0, 0), (badge_width, badge_height)],
            radius=corner_radius,
            fill=(0, 0, 0, background_opacity)  # Customizable opacity
        )

        # Load fonts - scale with badge size and custom multiplier
        font_large_size = int(badge_width * 0.20 * font_multiplier)  # 20% of badge width * multiplier
        font_small_size = int(badge_width * 0.10 * font_multiplier)  # 10% of badge width * multiplier

        # Use custom font family if specified (unified badge mode)
        font_family = style.get('font_family', 'DejaVu Sans Bold')
        font_path = self.FONT_PATHS.get(font_family, self.FONT_PATHS['DejaVu Sans Bold'])

        try:
            font_large = ImageFont.truetype(font_path, font_large_size)
            # Use regular for small text
            font_small = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_small_size
            )
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # Draw each rating
        y_offset = padding
        for source, rating in ratings.items():
            self._draw_rating_row(
                badge, draw, source, rating,
                y_offset, badge_width, row_height,
                font_large, font_small, badge_width,  # Pass badge_width for scaling
                rating_color  # Pass custom rating color
            )
            y_offset += row_height

        return badge

    def create_individual_badge(
        self,
        source: str,
        rating: float,
        poster_size: Tuple[int, int],
        badge_style: Optional[Dict[str, Any]] = None
    ) -> Image.Image:
        """
        Create a single compact badge with logo on top, rating underneath

        Args:
            source: Rating source ('tmdb', 'imdb', 'rt_critic', 'rt_audience')
            rating: Rating value
            poster_size: (width, height) of poster for scaling
            badge_style: Optional styling options

        Returns:
            PIL Image with transparent background
        """
        poster_width, poster_height = poster_size

        # Apply custom styling or use defaults
        style = badge_style or {}
        badge_size_percent = style.get('individual_badge_size', 12) / 100  # 12% of poster width by default
        font_multiplier = style.get('font_size_multiplier', 1.0)
        logo_multiplier = style.get('logo_size_multiplier', 1.0)
        rating_color_hex = style.get('rating_color', '#FFD700')  # Gold
        background_opacity = style.get('background_opacity', 128)

        # Convert hex color to RGB tuple
        rating_color = tuple(int(rating_color_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (255,)

        # Load template
        template_name = style.get('badge_template', 'default')
        template = BADGE_TEMPLATES.get(template_name, BADGE_TEMPLATES['default'])

        # Badge size - compact square-ish badge
        badge_width = int(poster_width * badge_size_percent)
        badge_height = int(badge_width * template.get('aspect_ratio', 1.4))

        # Create badge with transparent background
        badge = Image.new('RGBA', (badge_width, badge_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)

        # Draw background based on template
        corner_radius = int(badge_width * template.get('corner_radius_pct', 0.10))

        if not template.get('no_background', False):
            if template.get('gradient', False):
                # Gradient background: draw line by line with varying opacity
                top_opacity = template.get('gradient_top_opacity', 200)
                bottom_opacity = template.get('gradient_bottom_opacity', 80)
                for y in range(badge_height):
                    alpha = int(top_opacity + (bottom_opacity - top_opacity) * (y / badge_height))
                    draw.line([(0, y), (badge_width, y)], fill=(0, 0, 0, alpha))
                # Apply rounded mask to clip the gradient
                if corner_radius > 0:
                    mask = Image.new('L', (badge_width, badge_height), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.rounded_rectangle([(0, 0), (badge_width, badge_height)], radius=corner_radius, fill=255)
                    badge.putalpha(mask)
            else:
                draw.rounded_rectangle(
                    [(0, 0), (badge_width, badge_height)],
                    radius=corner_radius,
                    fill=(0, 0, 0, background_opacity)
                )

            # Draw border if template calls for it
            if template.get('border', False):
                border_width = max(1, int(badge_width * template.get('border_width_pct', 0.04)))
                draw.rounded_rectangle(
                    [(0, 0), (badge_width - 1, badge_height - 1)],
                    radius=corner_radius,
                    outline=rating_color,
                    width=border_width
                )

        # For RT scores, dynamically select logo based on score
        logo_key = source
        if source == 'rt_critic':
            logo_key = 'rt_fresh' if rating >= 60 else 'rt_rotten'
        elif source == 'rt_audience':
            logo_key = 'rt_audience_fresh' if rating >= 60 else 'rt_audience_rotten'

        # Draw logo in top section of badge (percentage from template)
        logo = self.logos.get(logo_key)
        logo_section_height = int(badge_height * template.get('logo_section_pct', 0.60))
        padding = int(badge_width * 0.1)

        if logo:
            # RT logos are bold graphic icons that appear much larger than TMDB/IMDb wordmarks
            # at the same pixel size — normalize so they feel visually equal at 1x
            LOGO_BASE_SCALE = {
                'tmdb': 1.00,
                'imdb': 1.00,
                'rt_fresh': 0.72,
                'rt_rotten': 0.72,
                'rt_audience_fresh': 0.72,
                'rt_audience_rotten': 0.72,
            }
            base_scale = LOGO_BASE_SCALE.get(logo_key, 1.0)
            # Calculate logo size to fit in top section, scaled by logo_size_multiplier
            max_logo_size = int(min(badge_width - (padding * 2), logo_section_height - padding) * logo_multiplier * base_scale)

            # Resize logo maintaining aspect ratio
            orig_width, orig_height = logo.size
            aspect_ratio = orig_width / orig_height

            if aspect_ratio > 1:
                # Wider than tall
                logo_width = max_logo_size
                logo_height = int(max_logo_size / aspect_ratio)
            else:
                # Taller than wide or square
                logo_height = max_logo_size
                logo_width = int(max_logo_size * aspect_ratio)

            logo_resized = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

            # Center logo in top section
            logo_x = (badge_width - logo_width) // 2
            logo_y = (logo_section_height - logo_height) // 2

            badge.paste(logo_resized, (logo_x, logo_y), logo_resized)

        # Draw rating in bottom 40% of badge
        number_section_top = logo_section_height
        number_section_height = badge_height - logo_section_height

        # Load font - use custom font family if specified
        font_size = int(badge_width * 0.35 * font_multiplier)  # 35% of badge width
        font_family = style.get('font_family', 'DejaVu Sans Bold')
        font_path = self.FONT_PATHS.get(font_family, self.FONT_PATHS['DejaVu Sans Bold'])

        try:
            font_rating = ImageFont.truetype(font_path, font_size)
            # Use regular variant for percent symbol (always DejaVu Sans for consistency)
            font_percent = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(font_size * 0.6)
            )
        except:
            font_rating = ImageFont.load_default()
            font_percent = ImageFont.load_default()

        # Format rating
        if source in ['rt_critic', 'rt_audience']:
            rating_text = f"{int(rating)}"
            percent_text = "%"
        else:
            rating_text = f"{rating:.1f}"
            percent_text = ""

        # Center position in bottom section
        center_x = badge_width // 2
        center_y = number_section_top + (number_section_height // 2)

        # Calculate total text width if there's a percent sign
        if percent_text:
            rating_bbox = draw.textbbox((0, 0), rating_text, font=font_rating)
            percent_bbox = draw.textbbox((0, 0), percent_text, font=font_percent)
            total_width = (rating_bbox[2] - rating_bbox[0]) + (percent_bbox[2] - percent_bbox[0]) + 2

            # Draw number (left side)
            self._draw_text_with_shadow(
                draw,
                (center_x - total_width // 2, center_y),
                rating_text,
                font_rating,
                rating_color,
                shadow_offset=max(2, int(badge_width * 0.02)),
                anchor="lm"
            )

            # Draw % (right side)
            self._draw_text_with_shadow(
                draw,
                (center_x + total_width // 2 - (percent_bbox[2] - percent_bbox[0]), center_y + int(font_size * 0.1)),
                percent_text,
                font_percent,
                (255, 255, 255, 255),
                shadow_offset=max(1, int(badge_width * 0.01)),
                anchor="lm"
            )
        else:
            # Just center the number
            self._draw_text_with_shadow(
                draw,
                (center_x, center_y),
                rating_text,
                font_rating,
                rating_color,
                shadow_offset=max(2, int(badge_width * 0.02)),
                anchor="mm"  # Middle-middle anchor
            )

        return badge

    def _draw_rating_row(
        self,
        badge: Image.Image,
        draw: ImageDraw.Draw,
        source: str,
        rating: float,
        y_offset: int,
        badge_width: int,
        row_height: int,
        font_large: ImageFont.FreeTypeFont,
        font_small: ImageFont.FreeTypeFont,
        scale_width: int,  # Badge width for scaling
        rating_color: Tuple[int, int, int, int] = (255, 215, 0, 255)  # Default gold
    ):
        """Draw a single rating row with logo and score"""
        x_padding = int(scale_width * 0.03)  # Scale padding

        # For RT scores, dynamically select logo based on score AND source
        logo_key = source
        if source in ['rt', 'rt_critic']:
            # RT Critic uses tomato logos
            if rating >= 60:
                logo_key = 'rt_fresh'
            else:
                logo_key = 'rt_rotten'
        elif source == 'rt_audience':
            # RT Audience uses popcorn logos
            if rating >= 60:
                logo_key = 'rt_audience_fresh'
            else:
                logo_key = 'rt_audience_rotten'

        # Draw logo - scale with badge size for consistency
        logo = self.logos.get(logo_key)
        max_logo_width = int(scale_width * 0.40)   # 40% of badge width max
        max_logo_height = int(scale_width * 0.20)  # 20% of badge width max

        # Make RT audience logos bigger (popcorn has more negative space)
        if source == 'rt_audience':
            # Spilled popcorn (rotten) needs to be bigger, standing (fresh) slightly bigger
            if logo_key == 'rt_audience_rotten':
                max_logo_width = int(max_logo_width * 1.3)
                max_logo_height = int(max_logo_height * 1.3)
            else:  # rt_audience_fresh
                max_logo_width = int(max_logo_width * 1.2)
                max_logo_height = int(max_logo_height * 1.2)

        if logo:
            # Calculate resize keeping aspect ratio
            orig_width, orig_height = logo.size
            aspect_ratio = orig_width / orig_height

            # Fit within max dimensions while maintaining aspect ratio
            if aspect_ratio > (max_logo_width / max_logo_height):
                # Width is the limiting factor
                logo_width = max_logo_width
                logo_height = int(max_logo_width / aspect_ratio)
            else:
                # Height is the limiting factor
                logo_height = max_logo_height
                logo_width = int(max_logo_height * aspect_ratio)

            # Resize logo maintaining aspect ratio
            logo_resized = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

            # Left-align all logos for consistency (only center vertically)
            logo_x = x_padding
            logo_y = y_offset + (row_height - logo_height) // 2

            # Paste logo (use logo as mask for transparency)
            badge.paste(logo_resized, (logo_x, logo_y), logo_resized)
        else:
            # Fallback: draw source name if no logo
            self._draw_text_with_shadow(
                draw,
                (x_padding, y_offset + row_height // 2),
                source.upper(),
                font_small,
                (255, 255, 255, 255)
            )

        # Draw rating score with drop shadow (no background!)
        # Scale shadow based on badge width
        shadow_large = int(scale_width * 0.01)  # 1% of width
        shadow_small = int(scale_width * 0.005)  # 0.5% of width

        if source in ['rt', 'rt_critic', 'rt_audience']:
            # Rotten Tomatoes is percentage - split number and % symbol
            rating_number = f"{int(rating)}"
            percent_symbol = "%"

            # Position to align with TMDB/IMDb scores
            rating_x = int(badge_width * 0.80)  # 80% across badge for better alignment
            rating_y = y_offset + (row_height // 2)

            # Get text sizes for alignment
            number_bbox = draw.textbbox((0, 0), rating_number, font=font_large)
            percent_bbox = draw.textbbox((0, 0), percent_symbol, font=font_small)

            total_width = (number_bbox[2] - number_bbox[0]) + (percent_bbox[2] - percent_bbox[0]) + int(scale_width * 0.01)

            # Draw rating number with shadow (GOLD text, large)
            self._draw_text_with_shadow(
                draw,
                (rating_x - total_width, rating_y),
                rating_number,
                font_large,
                rating_color,  # Custom rating color
                shadow_offset=shadow_large,
                anchor="lm"
            )

            # Draw % symbol with shadow (WHITE text, small)
            self._draw_text_with_shadow(
                draw,
                (rating_x - (percent_bbox[2] - percent_bbox[0]), rating_y + int(scale_width * 0.02)),
                percent_symbol,
                font_small,
                (255, 255, 255, 255),  # White
                shadow_offset=shadow_small,
                anchor="lm"
            )
        else:
            # TMDB and IMDb - just show the number (cleaner design)
            rating_text = f"{rating:.1f}"

            # Position at right edge (align with RT percentages)
            rating_x = badge_width - x_padding
            rating_y = y_offset + (row_height // 2)

            # Get text size for right alignment
            rating_bbox = draw.textbbox((0, 0), rating_text, font=font_large)
            text_width = rating_bbox[2] - rating_bbox[0]

            # Draw rating number with shadow (GOLD text) - right aligned
            self._draw_text_with_shadow(
                draw,
                (rating_x - text_width, rating_y),
                rating_text,
                font_large,
                rating_color,  # Custom rating color
                shadow_offset=shadow_large,
                anchor="lm"
            )

    def apply_to_poster(
        self,
        poster_path: str,
        ratings: Dict[str, float],
        output_path: str,
        position: str = 'northeast',
        badge_style: Optional[Dict[str, Any]] = None,
        badge_positions: Optional[Dict[str, Dict[str, float]]] = None
    ) -> Image.Image:
        """
        Apply rating badge(s) to poster

        Supports two modes:
        1. Unified badge mode (legacy): Single badge with all ratings
        2. Individual badge mode (new): Separate badge for each rating source

        Args:
            poster_path: Path to poster image
            ratings: Dict of ratings {'tmdb': 7.2, 'imdb': 7.5, 'rt_critic': 85, 'rt_audience': 92}
            output_path: Output path
            position: Badge position for unified mode (legacy)
            badge_style: Optional styling options
            badge_positions: Optional dict for individual mode. Format:
                            {'tmdb': {'x': 5, 'y': 5}, 'imdb': {'x': 20, 'y': 5}, ...}
                            If source key exists, that badge is enabled at that position.
                            X/Y are percentages (0-100) of poster dimensions.

        Returns:
            PIL Image
        """
        # Open poster
        poster = Image.open(poster_path).convert('RGBA')
        poster_width, poster_height = poster.size

        # Optional status text overlay (cancelled / renewed / current)
        status_overlay = (badge_style or {}).get('status_overlay', 'none')
        status_position = (badge_style or {}).get('status_position', 'center')
        status_rotation = (badge_style or {}).get('status_rotation', 0)

        # MODE 1: Individual badges (new 4-badge system)
        if badge_positions:
            for source, rating in ratings.items():
                # Check if this source is enabled (key exists in badge_positions)
                if source not in badge_positions:
                    continue

                pos = badge_positions[source]
                x_percent = pos.get('x', 5)
                y_percent = pos.get('y', 5)

                # Create individual badge
                badge = self.create_individual_badge(
                    source=source,
                    rating=rating,
                    poster_size=(poster_width, poster_height),
                    badge_style=badge_style
                )

                # Convert percentage to pixels
                badge_x = int((x_percent / 100) * poster_width)
                badge_y = int((y_percent / 100) * poster_height)

                # Composite badge onto poster
                poster.paste(badge, (badge_x, badge_y), badge)

            self._apply_status_overlay(poster, status_overlay, status_position, status_rotation)

            # Save
            poster_rgb = poster.convert('RGB')
            poster_rgb.save(output_path, 'JPEG', quality=95)

            enabled_sources = ', '.join([f'{k.upper()}: {v}' for k, v in ratings.items() if k in badge_positions])
            print(f"✓ Applied individual rating badges: {output_path}")
            print(f"  Enabled badges: {enabled_sources}")

            return poster

        # MODE 2: Unified badge (legacy - backward compatible)
        else:
            # Create unified badge with all ratings
            badge = self.create_multi_rating_badge(
                ratings=ratings,
                poster_size=(poster_width, poster_height),
                position=position,
                badge_style=badge_style
            )

            badge_width, badge_height = badge.size

            # Calculate position - handle both string positions and dict coordinates
            if isinstance(position, dict):
                # Free positioning with percentage coordinates
                x_percent = position.get('x', 2)
                y_percent = position.get('y', 2)
                badge_x = int((x_percent / 100) * poster_width)
                badge_y = int((y_percent / 100) * poster_height)
            else:
                # Named corner positions (string)
                offset_x = int(poster_width * 0.02)  # 2% from edges (close to edge)
                offset_y = int(poster_height * 0.02)

                positions = {
                    'northeast': (poster_width - badge_width - offset_x, offset_y),
                    'northwest': (offset_x, offset_y),
                    'southeast': (poster_width - badge_width - offset_x, poster_height - badge_height - offset_y),
                    'southwest': (offset_x, poster_height - badge_height - offset_y)
                }

                badge_x, badge_y = positions.get(position, positions['northwest'])

            # Composite badge onto poster
            poster.paste(badge, (badge_x, badge_y), badge)

            self._apply_status_overlay(poster, status_overlay, status_position, status_rotation)

            # Save
            poster_rgb = poster.convert('RGB')
            poster_rgb.save(output_path, 'JPEG', quality=95)

            print(f"✓ Applied multi-rating overlay: {output_path}")
            print(f"  Position: {position} ({badge_x}, {badge_y})")
            print(f"  Ratings: {', '.join([f'{k.upper()}: {v}' for k, v in ratings.items()])}")

            return poster

    def _apply_status_overlay(self, poster: Image.Image, status_overlay: Optional[str], status_position = 'center', status_rotation: int = 0):
        """Apply a status text overlay with dark background on a poster."""
        if not status_overlay:
            return

        status_key = status_overlay.lower().strip()
        if status_key == 'none' or status_key not in self.STATUS_STYLES:
            return

        style = self.STATUS_STYLES[status_key]
        poster_width, poster_height = poster.size
        font_size = max(24, int(min(poster_width, poster_height) * 0.12))

        try:
            font = ImageFont.truetype(self.FONT_PATHS['DejaVu Sans Bold'], font_size)
        except Exception:
            font = ImageFont.load_default()

        # Resolve center coordinates from position
        if isinstance(status_position, dict):
            cx = int((status_position.get('x', 50) / 100) * poster_width)
            cy = int((status_position.get('y', 50) / 100) * poster_height)
        else:
            margin_x = int(poster_width * 0.05)
            margin_y = int(poster_height * 0.08)
            named = {
                'center':       (poster_width // 2, poster_height // 2),
                'top':          (poster_width // 2, margin_y),
                'bottom':       (poster_width // 2, poster_height - margin_y),
                'top-left':     (margin_x, margin_y),
                'top-right':    (poster_width - margin_x, margin_y),
                'bottom-left':  (margin_x, poster_height - margin_y),
                'bottom-right': (poster_width - margin_x, poster_height - margin_y),
            }
            cx, cy = named.get(status_position, named['center'])

        # Draw text + background on a separate layer, then rotate if needed
        # Use a large square canvas so rotation doesn't clip
        canvas_size = max(poster_width, poster_height) * 2
        text_layer = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_layer)
        tcx, tcy = canvas_size // 2, canvas_size // 2

        # Measure text for background pill
        bbox = draw.textbbox((0, 0), style['label'], font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad_x = int(tw * 0.25)
        pad_y = int(th * 0.35)

        # Dark background pill
        bg_rect = [
            tcx - tw // 2 - pad_x,
            tcy - th // 2 - pad_y,
            tcx + tw // 2 + pad_x,
            tcy + th // 2 + pad_y,
        ]
        draw.rounded_rectangle(bg_rect, radius=int(th * 0.3), fill=(0, 0, 0, 180))

        # Text
        draw.text(
            (tcx, tcy),
            style['label'],
            font=font,
            fill=style['color'],
            anchor='mm',
            stroke_width=max(1, int(font_size * 0.03)),
            stroke_fill=(0, 0, 0, 210)
        )

        # Rotate the text layer if needed
        rotation = int(status_rotation or 0)
        if rotation:
            text_layer = text_layer.rotate(-rotation, resample=Image.Resampling.BICUBIC, expand=False)

        # Crop from center of large canvas and composite onto poster at (cx, cy)
        half_w, half_h = poster_width // 2, poster_height // 2
        left = tcx - cx
        top = tcy - cy
        cropped = text_layer.crop((left, top, left + poster_width, top + poster_height))
        poster.alpha_composite(cropped)
