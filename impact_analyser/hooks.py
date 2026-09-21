app_name = "impact_analyser"
app_title = "Impact Analyzer"
app_publisher = "Team Thendral"
app_description = "Impact Analyzer for Frappe and ERPNext codebases"
app_email = "jamunadevig4@gmail.com"
app_license = "MIT"
app_icon = "octicon octicon-search"
app_color = "#2563eb"

# Apps
# ------------------

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "impact_analyser",
		"logo": "/assets/impact_analyser/images/icon.svg",
		"title": "Impact Analyzer",
		"route": "/app/impact-analyzer",
	}
]

# brand_html = '<div><img src="/assets/public/images/dead-code-eliminator-logo.png">Dead Code Eliminator</div>'

brand_html = '''
<div style="display:flex; align-items:center; gap:12px;">
    <img src="/assets/impact_analyser/images/dead-code-eliminator-logo.png"
         style="height:60px; width:60px; object-fit:contain;">
    <span style="font-size:20px; font-weight:600;">
        Dead Code Eliminator
    </span>
</div>
'''