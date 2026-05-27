"""RTK-enhanced extractors for archolith-context.

When archolith-context is installed alongside archolith-rtk, these
extractors self-register via entry points and override the built-in
extractors for ``Bash`` and ``Read`` tools.
"""

from archolith_rtk.extractors.bash import BashRtkExtractor as BashRtkExtractor
from archolith_rtk.extractors.read_file import ReadFileRtkExtractor as ReadFileRtkExtractor
