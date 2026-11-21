"""Shared Hypothesis profile: few examples and no deadline keep the suite fast."""
from hypothesis import HealthCheck, settings

settings.register_profile(
    "default",
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
settings.load_profile("default")
