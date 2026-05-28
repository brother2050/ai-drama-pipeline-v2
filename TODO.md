# TODO — 待开发功能 & 已知缺陷

> 更新：2026-05-28

## 已修复

- [x] 批量生成定妆照未回写 YAML reference_images（pipeline/portraits.py）
- [x] 自动定妆照 ensure_portrait 未回写 YAML reference_images（engines/portrait.py）
- [x] 定妆照只生成主图，不遍历 outfits 生成各服装参考图
- [x] 删除图片后重生成得到相同图片（workflow seed 固定为 0）
- [x] `_generating` set 线程安全问题（engines/portrait.py）
- [x] `_proj_cache` 全局变量线程安全问题（web/routers/api.py）

## 缺陷

### HIGH — YAML 写入非原子操作

**位置**: `pipeline/tasks.py`, `engines/portrait.py`, `web/routers/api.py`, `infra/config.py`

所有 `yaml.dump(data, f)` 直接写目标文件。如果进程在写入中途崩溃（OOM、kill、断电），YAML 文件会损坏丢失全部配置。

**修复方案**: 参照 `engines/storyboard.py::save_storyboard()` 的 temp file + `os.replace` 模式：
```python
import tempfile, os
fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.dump(data, f, ...)
    os.replace(tmp, str(path))
except BaseException:
    try: os.unlink(tmp)
    except OSError: pass
    raise
```

**影响范围**: 约 15 处 yaml.dump 调用

### MEDIUM — Rate limit 内存泄漏

**位置**: `web/routers/api.py::_check_rate_limit()`

每次请求都遍历全量 IP 做清理，高并发下 O(N) 开销。低流量下过期 IP 清理及时，但极端场景（大量不同 IP 访问后停止）会残留。

**修复方案**: 加计数器，每 100 次请求或每隔 60s 才做一次全量清理。

### MEDIUM — ensure_portrait 不生成 outfit 图

**位置**: `engines/portrait.py::ensure_portrait()`

管线自动触发的定妆照只生成主图，不遍历 outfits。与 `portrait_single_task` 行为不一致。

**修复方案**: 复用 `pipeline/portraits.py::_generate_outfit()` 逻辑。

### MEDIUM — Seko 图片下载无重试

**位置**: `pipeline/tasks.py::_download_seko_image()`

使用 `urllib.request` 单次下载，网络抖动直接失败。

**修复方案**: 加 3 次指数退避重试。

### MEDIUM — post/production.py 中间文件残留

**位置**: `post/production.py::run_post()`

如果进程在 concat 之后、cleanup 之前崩溃，中间文件（_concat.mp4, _subtitled.mp4 等）会残留。

**修复方案**: 启动时扫描并清理已知模式的中间文件。

### LOW — 多处 except Exception: pass 静默吞错

**位置**: `api/registry.py:172`, `web/routers/api.py:115/587/628/650` 等

部分 `except Exception: pass` 会隐藏潜在问题。应至少 `logger.debug` 记录。

### LOW — _load_env 重复调用

**位置**: `cli.py`

`_load_env()` 在 serve/worker/status/preview 等多个命令中调用，但 `dotenv.load_dotenv(override=False)` 天然幂等，无功能影响。
