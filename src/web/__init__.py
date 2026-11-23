"""Web UI package — split out of the former single-file src/web_ui.py.

web_ui.py remains the entrypoint (page routes, route table, app assembly,
main()). The implementation lives here:

    web.db        — connection, schema, conversation/persona SQL helpers
    web.security  — auth middleware + env-flag stack assembly
    web.assets    — static-file tags (CSS / JS under web/static), the SVG mark
    web.render    — per-page HTML rendering
    web.api       — /api/* route handlers
"""



