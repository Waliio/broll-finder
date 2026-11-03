"""Build variant flag.

PUBLIC_BUILD = False -> private build: the BRAIN tab is visible and the
brain files are editable, as before.
PUBLIC_BUILD = True -> public build: the BRAIN tab is hidden and the
brain APIs are locked. Scans still work, using the brain embedded in
engine/default_brain.py, but no brain text is shown, saved, or written
to the user's PC in readable form.

This file is committed as False. The GitHub workflow overwrites it in
the runner only (never committed) when a public build is requested, so
the public flag never has to be edited by hand.
"""

PUBLIC_BUILD = False
