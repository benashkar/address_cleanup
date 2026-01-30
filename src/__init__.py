"""Address deduplication package."""
from .normalizer import AddressNormalizer
from .duplicate_detector import DuplicateDetector
from .unit_patterns import parse_unit, ParsedUnit
