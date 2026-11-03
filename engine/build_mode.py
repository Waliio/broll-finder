"""Build variant flag.

PUBLIC_BUILD = False -> private build: BRAIN tab visible, brain editable.
PUBLIC_BUILD = True  -> public build: BRAIN tab hidden, brain APIs locked,
scans use the embedded brain only, no readable brain file is written.

Committed as False. The GitHub workflow overwrites this file in the
runner only (never committed) when a public build is requested.
"""

PUBLIC_BUILD = False
