# TODO — 待开发功能 & 已知缺陷

> 更新：2026-05-29

## 已修复（本次审查）

- [x] 批量生成定妆照未回写 YAML reference_images（pipeline/portraits.py）
- [x] 自动定妆照 ensure_portrait 未回写 YAML reference_images（engines/portrait.py）
- [x] 定妆照只生成主图，不遍历 outfits 生成各服装参考图
- [x] 删除图片后重生成得到相同图片（workflow seed 固定为 0）
- [x] `_generating` set 线程安全问题（engines/portrait.py）
- [x] `_proj_cache` 全局变量线程安全问题（web/routers/api.py）
- [x] **[HIGH]** YAML 写入非原子操作 → 全量替换为 `save_yaml()`（temp file + os.replace）
- [x] **[MEDIUM]** Rate limit 每次请求 O(N) 全量清理 → 改为每 100 次清理一次
- [x] **[MEDIUM]** Seko 图片下载无重试 → 3 次指数退避重试
- [x] **[MEDIUM]** post/production.py 中间文件残留 → 启动时清理
- [x] **[LOW]** 多处 except Exception: pass 静默吞错 → 关键位置加 logger.debug
- [x] **[MEDIUM]** ensure_portrait 管线中不生成 outfit 图 → 新增 `portraits.auto_outfit` 配置项，由用户决定

## 剩余缺陷

（暂无）
