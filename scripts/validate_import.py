#!/usr/bin/env python3
"""
导入前校验工具 — 检查 LLM 生成的角色/场景/分镜文件格式是否正确

用法:
  python scripts/validate_import.py <文件路径或目录>
  python scripts/validate_import.py characters.yaml scenes.yaml storyboard.csv
  python scripts/validate_import.py projects/default/config/characters/
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import yaml

# ── 校验规则 ──

ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
VALID_CAMERAS = {"固定", "缓慢推近", "跟随平移", "手持晃动", "环绕", "俯视", "仰视"}
VALID_SHOT_TYPES = {"特写", "近景", "中景", "过肩", "全身", "全景", "远景", "双人全景"}
VALID_EMOTIONS = {"happy", "sad", "worried", "surprised", "angry", "romantic", "calm", "determined", "serious", "neutral", "smug", "fearful", "action"}
VALID_GENDERS = {"male", "female", ""}

SB_REQUIRED = ["episode", "shot_id", "scene", "characters", "action", "dialogue"]


def check(ok: bool, msg: str, errors: list[str], warnings: list[str], is_error: bool = True):
    if not ok:
        (errors if is_error else warnings).append(msg)


def validate_character_yaml(path: Path) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        return [f"YAML 语法错误: {e}"], []

    char = data.get("character")
    if not char:
        return [f"缺少 'character' 顶级键"], []

    # 必填字段
    for field in ["id", "name", "gender", "appearance"]:
        check(field in char and char[field], f"缺少必填字段: {field}", errors, warnings)

    cid = char.get("id", "")
    check(bool(ID_RE.match(cid)) if cid else False,
          f"id '{cid}' 格式错误（仅允许字母、数字、下划线、连字符）", errors, warnings)

    gender = char.get("gender", "")
    check(gender in VALID_GENDERS, f"gender '{gender}' 无效（应为 male/female）", errors, warnings)

    appearance = char.get("appearance", "")
    check(len(appearance) >= 10, f"appearance 太短（{len(appearance)}字，建议50-100字）", errors, warnings, False)

    # outfits
    outfits = char.get("outfits")
    if outfits:
        check(isinstance(outfits, dict), "outfits 应为字典格式", errors, warnings)
        check("default" in outfits, "outfits 缺少 'default' 键", errors, warnings)
        for key, val in outfits.items():
            if isinstance(val, dict):
                check("description" in val, f"outfits.{key} 缺少 'description'", errors, warnings)
            elif isinstance(val, str):
                warnings.append(f"outfits.{key} 是字符串格式，建议改为 dict: {{description: '...', reference_images: []}}")
    else:
        warnings.append("未定义 outfits（建议至少定义 default）")

    # voice
    voice = char.get("voice")
    if voice:
        check(isinstance(voice, dict), "voice 应为字典格式", errors, warnings)
        if isinstance(voice, dict):
            check("voice_description" in voice, "voice 缺少 'voice_description'", errors, warnings)
    else:
        warnings.append("未定义 voice")

    return errors, warnings


def validate_scene_yaml(path: Path) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        return [f"YAML 语法错误: {e}"], []

    scene = data.get("scene")
    if not scene:
        return [f"缺少 'scene' 顶级键"], []

    for field in ["id", "name", "description"]:
        check(field in scene and scene[field], f"缺少必填字段: {field}", errors, warnings)

    sid = scene.get("id", "")
    check(bool(ID_RE.match(sid)) if sid else False,
          f"id '{sid}' 格式错误（仅允许字母、数字、下划线、连字符）", errors, warnings)

    desc = scene.get("description", "")
    check(len(desc) >= 10, f"description 太短（{len(desc)}字，建议50-100字）", errors, warnings, False)

    lighting = scene.get("lighting", "")
    check(bool(lighting), "缺少 lighting 字段", errors, warnings, False)

    return errors, warnings


def validate_storyboard_csv(path: Path) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        return [f"CSV 读取失败: {e}"], []

    if not rows:
        return ["CSV 为空（没有镜头数据）"], []

    headers = set(rows[0].keys())
    for field in SB_REQUIRED:
        check(field in headers, f"CSV 缺少列: {field}", errors, warnings)

    shot_ids = set()
    for i, row in enumerate(rows, 1):
        sid = row.get("shot_id", "")
        check(bool(sid), f"第{i}行: shot_id 为空", errors, warnings)
        check(sid not in shot_ids, f"第{i}行: shot_id '{sid}' 重复", errors, warnings)
        shot_ids.add(sid)

        check(bool(ID_RE.match(sid)) if sid else False,
              f"第{i}行: shot_id '{sid}' 格式错误", errors, warnings)

        scene = row.get("scene", "")
        check(bool(scene), f"第{i}行: scene 为空", errors, warnings)

        chars = row.get("characters", "")
        check(bool(chars), f"第{i}行: characters 为空", errors, warnings)

        # 检查 characters 中的 ID 格式
        if chars:
            for cid in chars.split("+"):
                cid = cid.strip()
                check(bool(ID_RE.match(cid)) if cid else False,
                      f"第{i}行: characters ID '{cid}' 格式错误", errors, warnings)

        dur = row.get("duration", "")
        if dur:
            try:
                d = int(dur)
                check(2 <= d <= 8, f"第{i}行: duration={d} 超出范围 [2,8]", errors, warnings, False)
            except ValueError:
                check(False, f"第{i}行: duration '{dur}' 不是数字", errors, warnings)

        cam = row.get("camera", "")
        if cam:
            check(cam in VALID_CAMERAS, f"第{i}行: camera '{cam}' 不在可选值中", errors, warnings, False)

        st = row.get("shot_type", "")
        if st:
            check(st in VALID_SHOT_TYPES, f"第{i}行: shot_type '{st}' 不在可选值中", errors, warnings, False)

        emo = row.get("emotion", "")
        if emo:
            check(emo in VALID_EMOTIONS, f"第{i}行: emotion '{emo}' 不在可选值中", errors, warnings, False)

    total_dur = sum(int(r.get("duration", 4) or 4) for r in rows)
    if total_dur < 30:
        warnings.append(f"总时长仅 {total_dur}s，可能太短（建议 60-120s）")

    return errors, warnings


def validate_storyboard_json(path: Path) -> tuple[list[str], list[str]]:
    """校验 JSON 格式的分镜表"""
    errors, warnings = [], []
    try:
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return [f"JSON 解析失败: {e}"], []

    if isinstance(data, dict):
        data = data.get("shots", [])
    if not isinstance(data, list):
        return ["JSON 应为数组或 {shots: [...]} 格式"], []

    # 写临时 CSV 用同样的校验逻辑
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        if data:
            fieldnames = list(data[0].keys())
            writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)
        tmp_path = Path(tmp.name)

    errors, warnings = validate_storyboard_csv(tmp_path)
    tmp_path.unlink(missing_ok=True)
    return errors, warnings


def validate_file(path: Path) -> bool:
    """校验单个文件，返回是否通过"""
    name = path.name
    print(f"\n📄 {path}")

    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "character" in data:
            errors, warnings = validate_character_yaml(path)
        elif "scene" in data:
            errors, warnings = validate_scene_yaml(path)
        else:
            errors, warnings = [f"未知 YAML 类型（缺少 character/scene 顶级键）"], []
    elif path.suffix == ".csv":
        errors, warnings = validate_storyboard_csv(path)
    elif path.suffix == ".json":
        errors, warnings = validate_storyboard_json(path)
    else:
        print(f"  ⏭ 跳过（不支持的文件类型）")
        return True

    for w in warnings:
        print(f"  ⚠ {w}")
    for e in errors:
        print(f"  ❌ {e}")

    if not errors and not warnings:
        print(f"  ✅ 格式正确")
    elif not errors:
        print(f"  ✅ 格式正确（有 {len(warnings)} 个警告）")
    else:
        print(f"  ❌ 发现 {len(errors)} 个错误，需要修正后才能导入")

    return len(errors) == 0


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/validate_import.py <文件或目录> [...]")
        print("示例:")
        print("  python scripts/validate_import.py linxia.yaml")
        print("  python scripts/validate_import.py projects/default/config/characters/")
        print("  python scripts/validate_import.py storyboard.csv")
        sys.exit(1)

    all_ok = True
    files = []

    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            files.extend(sorted(p.glob("*.yaml")))
            files.extend(sorted(p.glob("*.yml")))
            files.extend(sorted(p.glob("*.csv")))
            files.extend(sorted(p.glob("*.json")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"❌ 路径不存在: {arg}")
            all_ok = False

    if not files:
        print("未找到可校验的文件")
        sys.exit(1)

    print(f"🔍 校验 {len(files)} 个文件...")
    for f in files:
        if not validate_file(f):
            all_ok = False

    print(f"\n{'='*40}")
    if all_ok:
        print("✅ 全部通过！可以导入到管线中。")
    else:
        print("❌ 部分文件有错误，请修正后重新校验。")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
