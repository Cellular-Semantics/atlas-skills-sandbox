"""h5ad-obs: read the `obs` table out of a remote .h5ad over HTTP range requests.

Only the byte ranges backing /obs are fetched; X, layers, obsm, var and raw are
never touched. On a 476 MB atlas that is ~27 MB and ~8 s.
"""
from importlib import metadata as _metadata

from .profile import as_text, profile_frame, profile_local, profile_remote
from .reader import ReadStats, read_obs

# Read from the installed distribution metadata rather than duplicated here:
# a hand-maintained copy silently drifted from pyproject.toml during the split
# out of cap_skills, and `--version` then reported a release that did not exist.
try:
    __version__ = _metadata.version("h5ad-obs")
except _metadata.PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0+unknown"

__all__ = ["ReadStats", "__version__", "as_text", "profile_frame", "profile_local",
           "profile_remote", "read_obs"]
