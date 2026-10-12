"""Read Vectric CRV project files and write their 2D vectors as SVG or DXF."""

from .dxf import to_dxf
from .errors import CrvError, UnsupportedError
from .model import Document, Item, Layer, Path, Span
from .reader import read_bytes, read_file
from .svg import to_svg

__version__ = "0.1.0"
__all__ = ["read_file", "read_bytes", "to_svg", "to_dxf", "CrvError", "UnsupportedError",
           "Document", "Layer", "Item", "Path", "Span", "__version__"]
