"""Flask blueprints.

Routes parse input, call one service, and render. They open no
transactions of their own beyond session_scope and contain no business
rules, so the workflow behaves identically from the web, the demo script,
and the tests.
"""
