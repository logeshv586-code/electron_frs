from event.event_api import router
import json

routes_info = []
for route in router.routes:
    routes_info.append({
        "path": route.path,
        "methods": list(route.methods)
    })

print(json.dumps(routes_info, indent=2))
