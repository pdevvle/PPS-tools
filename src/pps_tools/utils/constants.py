"""Enums and constants for PPS-Tools."""

from enum import Enum


class ProductType(str, Enum):
    BUSINESS_CARDS = "business_cards"
    FLYERS = "flyers"
    POSTCARDS = "postcards"
    BROCHURES = "brochures"
    BOOKLETS = "booklets"
    PRESENTATION_FOLDERS = "presentation_folders"
    DOOR_HANGERS = "door_hangers"
    NOTEPADS = "notepads"
    LETTERHEAD = "letterhead"


class PaperType(str, Enum):
    PT_14 = "14pt"
    PT_16 = "16pt"
    GLOSS_100LB = "100lb_gloss"
    GLOSS_80LB = "80lb_gloss"
    UNCOATED_70LB = "70lb_uncoated"
    MATTE = "matte"
    GLOSSY = "glossy"
    LINEN = "linen"
    RECYCLED = "recycled"


class ColorMode(str, Enum):
    FULL_COLOR = "full_color"
    BW = "bw"
    SPOT = "spot"


class Sides(str, Enum):
    SINGLE = "single"
    DOUBLE = "double"


class Finish(str, Enum):
    NONE = "none"
    UV_COATING = "uv_coating"
    MATTE_FINISH = "matte_finish"
    SPOT_UV = "spot_uv"
    SOFT_TOUCH = "soft_touch"
    TRI_FOLD = "tri_fold"
    HALF_FOLD = "half_fold"
    SADDLE_STITCH = "saddle_stitch"


class ScrapeStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"


class DiscoveryMethod(str, Enum):
    SEARCH = "search"
    MANUAL = "manual"
    CRAWL = "crawl"
    CONFIG = "config"


class ReportType(str, Enum):
    COMPARISON = "comparison"
    TREND = "trend"
    DASHBOARD = "dashboard"


class ExportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    HTML = "html"
    TERMINAL = "terminal"
