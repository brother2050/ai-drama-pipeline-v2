"""批量调度"""
from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


def batch_run(orchestrator, shots: list[dict], episode: int, *,
              mode: str = "sequential", max_workers: int = 2) -> list[dict]:
    """批量执行镜头"""
    if mode == "parallel":
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(orchestrator.run_shot, s, episode): s for s in shots}
            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as e:
                    shot = futures[f]
                    results.append({"shot_id": shot.get("shot_id"), "status": "error", "error": str(e)})
        return results
    else:
        return [orchestrator.run_shot(s, episode) for s in shots]
