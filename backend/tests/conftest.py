import os

# Existing endpoint tests exercise RBAC with explicit synthetic headers. Runtime
# deployments keep this disabled and use signed demo-session tokens instead.
os.environ["ALLOW_LEGACY_AUTH_HEADERS"] = "true"
os.environ["DEMO_AUTH_SECRET"] = "caredelta-test-secret-isolated-from-runtime"
