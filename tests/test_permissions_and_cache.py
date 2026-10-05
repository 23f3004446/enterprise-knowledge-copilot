import numpy as np

from app.core.cache import SemanticAnswerCache
from app.core.permissions import allowed_access_levels, can_access


def test_role_permission_matrix() -> None:
    assert allowed_access_levels("EMPLOYEE") == {"PUBLIC", "EMPLOYEE"}
    assert can_access("MANAGER", "MANAGER")
    assert not can_access("MANAGER", "ADMIN")
    assert can_access("ADMIN", "ADMIN")
    assert not can_access("UNKNOWN", "PUBLIC")


def test_semantic_cache_isolated_by_role_and_permission_scope() -> None:
    cache = SemanticAnswerCache(ttl_seconds=30, similarity_threshold=0.9)
    vector = np.array([1.0, 0.0], dtype="float32")
    employee_scope = cache.scope_key(allowed_access_levels("EMPLOYEE"))
    manager_scope = cache.scope_key(allowed_access_levels("MANAGER"))
    cache.set(vector, "MANAGER", manager_scope, "model-v1", {"answer": "manager-only"})

    assert cache.get(vector, "EMPLOYEE", employee_scope, "model-v1") is None
    assert cache.get(vector, "MANAGER", manager_scope, "model-v1") == {"answer": "manager-only"}
    assert cache.get(vector, "MANAGER", manager_scope, "model-v2") is None
