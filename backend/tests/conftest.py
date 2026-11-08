import os
import tempfile

# The tests use the five seeded practice disputes. The running app does not (it shows real or recorded real ones).
os.environ["WARRANT_SEED_DEMO"] = "1"

# The tests never talk to PayPal and never read saved live disputes, even on a machine that has real sandbox keys.
for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_BASE_URL", "NVIDIA_API_KEY"):
    os.environ.pop(key, None)
os.environ["WARRANT_STATE_DIR"] = tempfile.mkdtemp(prefix="warrant-test-")
os.environ["WARRANT_RECORDED_FILE"] = os.path.join(os.environ["WARRANT_STATE_DIR"], "none.json")  # no recorded copy in tests
