"""Generated media shared by any agent that produces images.

Not re-exported from the package root: this needs the google-genai client,
which not every agent ships. Import the module directly.
"""

from .images import GeneratedImage, ImageRequest, generate_images

__all__ = ["GeneratedImage", "ImageRequest", "generate_images"]
