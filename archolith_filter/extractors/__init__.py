"""RTK-enhanced extractors for archolith-context.

When archolith-context is installed alongside archolith-filter, these
extractors self-register via entry points and override the built-in
extractors for ``Bash`` and ``Read`` tools.
"""

from archolith_filter.extractors.bash import BashRtkExtractor as BashRtkExtractor
from archolith_filter.extractors.read_file import ReadFileRtkExtractor as ReadFileRtkExtractor
