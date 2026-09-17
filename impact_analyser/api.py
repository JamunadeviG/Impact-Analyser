# Copyright (c) 2026, Team Thendral and contributors
# Proxy module — exposes API methods at the package root level
# so they are callable as `impact_analyser.api.*`
from impact_analyser.impact_analyser.api import (
	analyze,
	get_apps_list,
	get_run,
)
