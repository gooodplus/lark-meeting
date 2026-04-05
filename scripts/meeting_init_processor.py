#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
会议室初始化命令行工具。

流程：
1) 查询二级层级城市（TopN）
2) 选择城市
3) 选择城市下第三级层级
4) 再查询下一层并选择最终会议室层级
5) 写入 conf/meeting.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.lark_cli import LarkAPI


def _items_from_response(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (resp.get("data") or {}).get("items") or []


def _print_options(title: str, options: List[Dict[str, Any]]) -> None:
    print(f"\n{title}")
    for idx, item in enumerate(options, 1):
        name = item.get("name", "未知名称")
        rid = item.get("room_level_id", "")
        print(f"  [{idx}] {name} ({rid})")


def _normalize(s: str) -> str:
    return s.strip().lower()


def _pick_by_input(
    options: List[Dict[str, Any]],
    prompt: str,
    *,
    allow_text_match: bool = True,
    fallback_options: Optional[List[Dict[str, Any]]] = None,
    fallback_hint: str = "已切换到全量结果继续匹配。",
) -> Dict[str, Any]:
    if not options:
        raise ValueError("无可选项")

    while True:
        raw = input(prompt).strip()
        if not raw:
            print("输入不能为空，请重试。")
            continue

        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
            print(f"编号超出范围，请输入 1~{len(options)}。")
            continue

        if not allow_text_match:
            print("仅支持输入编号，请重试。")
            continue

        key = _normalize(raw)
        exact = [x for x in options if _normalize(str(x.get("name", ""))) == key]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            _print_options("匹配到多个同名项，请输入编号选择：", exact)
            options = exact
            continue

        fuzzy = [x for x in options if key in _normalize(str(x.get("name", "")))]
        if len(fuzzy) == 1:
            return fuzzy[0]
        if len(fuzzy) > 1:
            _print_options("匹配到多个候选项，请输入编号选择：", fuzzy)
            options = fuzzy
            continue

        # TopN 未匹配时，回退到全量结果再次匹配。
        if fallback_options and options is not fallback_options:
            options = fallback_options
            print(f"{fallback_hint}（共 {len(options)} 项）")
            exact = [x for x in options if _normalize(str(x.get("name", ""))) == key]
            if len(exact) == 1:
                return exact[0]
            if len(exact) > 1:
                _print_options("全量结果中匹配到多个同名项，请输入编号选择：", exact)
                options = exact
                continue

            fuzzy = [x for x in options if key in _normalize(str(x.get("name", "")))]
            if len(fuzzy) == 1:
                return fuzzy[0]
            if len(fuzzy) > 1:
                _print_options("全量结果中匹配到多个候选项，请输入编号选择：", fuzzy)
                options = fuzzy
                continue

        print("未匹配到候选项，请输入编号或更精确的名称。")


def _collect_level2_cities(api: LarkAPI, page_size: int) -> List[Dict[str, Any]]:
    """从根开始获取二级层级节点列表。"""
    resp = api.query_room_levels(parent_level_id=None, page_size=page_size, depth=2)
    level1 = _items_from_response(resp)

    level2: List[Dict[str, Any]] = []
    for node in level1:
        for child in node.get("children") or []:
            level2.append(child)

    # 某些租户结构可能根下直接是城市，兜底用一级节点。
    if not level2:
        level2 = level1
    return level2


def _write_meeting_config(
    city: Dict[str, Any],
    workplace_level: Dict[str, Any],
    floor_level: Dict[str, Any],
    rooms: List[Dict[str, Any]],
) -> Path:
    conf_dir = _ROOT / "conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf_path = conf_dir / "meeting.json"

    payload = {
        "selected_city": {
            "name": city.get("name"),
            "room_level_id": city.get("room_level_id"),
        },
        "selected_workplace": {
            "name": workplace_level.get("name"),
            "room_level_id": workplace_level.get("room_level_id"),
            "parent_id": workplace_level.get("parent_id"),
        },
        "selected_floor": {
            "name": floor_level.get("name"),
            "room_level_id": floor_level.get("room_level_id"),
            "parent_id": floor_level.get("parent_id"),
        },
        "selected_level": {
            "name": floor_level.get("name"),
            "room_level_id": floor_level.get("room_level_id"),
            "parent_id": floor_level.get("parent_id"),
        },
        "level_path": [
            {"name": city.get("name"), "room_level_id": city.get("room_level_id")},
            {
                "name": workplace_level.get("name"),
                "room_level_id": workplace_level.get("room_level_id"),
            },
            {
                "name": floor_level.get("name"),
                "room_level_id": floor_level.get("room_level_id"),
            },
        ],
        "rooms": rooms,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    conf_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return conf_path


def _extract_floor_number(text: str) -> Optional[int]:
    if not text:
        return None
    s = text.lower()
    m = re.search(r"(\d+)\s*(?:f|层|楼)", s)
    if m:
        return int(m.group(1))
    m2 = re.search(r"(?:f|层|楼)\s*(\d+)", s)
    if m2:
        return int(m2.group(1))
    return None


def _collect_rooms_by_workplace(api: LarkAPI, workplace_id: str, page_size: int) -> List[Dict[str, Any]]:
    rooms: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        resp = api.search_rooms(
            room_level_id=workplace_id,
            page_size=page_size,
            page_token=page_token,
        )
        data = resp.get("data") or {}
        # rooms/search 返回字段为 data.rooms（不是 data.items）
        batch = data.get("rooms") or []
        rooms.extend(batch)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return rooms


def _sorted_rooms_for_floor(
    rooms: List[Dict[str, Any]],
    selected_floor_id: str,
    floor_order: Dict[str, int],
) -> List[Dict[str, Any]]:
    selected_idx = floor_order.get(selected_floor_id, 0)

    def _key(room: Dict[str, Any]) -> Any:
        room_floor_id = str(room.get("room_level_id", ""))
        if room_floor_id == selected_floor_id:
            return (0, 0, str(room.get("name", "")))

        # 按楼层顺序相邻优先（基于楼层列表顺序）
        if room_floor_id in floor_order:
            return (1, abs(floor_order[room_floor_id] - selected_idx), str(room.get("name", "")))

        # 兜底：未知楼层 ID 排后
        return (2, 999, str(room.get("name", "")))

    return sorted(rooms, key=_key)


def _is_blacklisted_room(room: Dict[str, Any]) -> bool:
    name = str(room.get("name") or "")
    if "面试间" in name:
        return True

    capacity = room.get("capacity")
    try:
        if capacity is not None and int(capacity) > 30:
            return True
    except (TypeError, ValueError):
        pass

    return False


def _compact_room(
    room: Dict[str, Any],
    floor_name_by_id: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    rid = room.get("room_id") or room.get("id")
    name = room.get("name")
    room_level_id = str(room.get("room_level_id") or "")
    if not rid or not name:
        return None
    floor_name = floor_name_by_id.get(room_level_id, "")
    return {
        "room_id": rid,
        "name": name,
        "room_level_id": room_level_id,
        "floor_name": floor_name,
    }


def run_init(page_size: int = 100, top_n: int = 10) -> None:
    api = LarkAPI()

    # 1) 取二级层级城市 topN
    cities = _collect_level2_cities(api, page_size=page_size)
    if not cities:
        raise RuntimeError("未获取到任何层级数据，无法初始化。")
    city_candidates = cities[:top_n]
    _print_options(f"请选择所在城市（Top {len(city_candidates)}）：", city_candidates)
    city = _pick_by_input(
        city_candidates,
        "请输入城市编号或名称：",
        fallback_options=cities,
        fallback_hint="Top 候选未匹配",
    )

    # 2) 城市下一级（第三级：职场）
    city_id = city.get("room_level_id")
    if not city_id:
        raise RuntimeError("城市节点缺少 room_level_id。")
    level3_resp = api.query_room_levels(parent_level_id=city_id, page_size=page_size, depth=1)
    level3_list = _items_from_response(level3_resp)
    if not level3_list:
        raise RuntimeError("该城市下无可选层级，初始化终止。")
    _print_options("请选择职场层级（第三级）：", level3_list)
    workplace_level = _pick_by_input(level3_list, "请输入职场编号或名称：")

    # 3) 职场下一级（楼层）
    workplace_id = workplace_level.get("room_level_id")
    if not workplace_id:
        raise RuntimeError("职场节点缺少 room_level_id。")
    floor_resp = api.query_room_levels(parent_level_id=workplace_id, page_size=page_size, depth=1)
    floor_candidates = _items_from_response(floor_resp)
    if not floor_candidates:
        raise RuntimeError("该职场下无楼层层级，初始化终止。")
    _print_options("请选择楼层层级：", floor_candidates)
    floor_level = _pick_by_input(floor_candidates, "请输入楼层编号或名称：")

    # 4) 以职场层级搜索会议室，并按楼层邻近排序（优先选中楼层）
    rooms = _collect_rooms_by_workplace(api, workplace_id, page_size)
    floor_order = {
        str(item.get("room_level_id")): idx
        for idx, item in enumerate(floor_candidates)
        if item.get("room_level_id")
    }
    floor_name_by_id = {
        str(item.get("room_level_id")): str(item.get("name") or "")
        for item in floor_candidates
        if item.get("room_level_id")
    }
    selected_floor_id = str(floor_level.get("room_level_id") or "")
    sorted_rooms = _sorted_rooms_for_floor(rooms, selected_floor_id, floor_order)
    filtered_rooms = [room for room in sorted_rooms if not _is_blacklisted_room(room)]
    compact_rooms = []
    for room in filtered_rooms:
        item = _compact_room(room, floor_name_by_id)
        if item:
            compact_rooms.append(item)

    conf_path = _write_meeting_config(city, workplace_level, floor_level, compact_rooms)
    print("\n初始化完成。")
    print(f"- 城市: {city.get('name')}")
    print(f"- 职场: {workplace_level.get('name')}")
    print(f"- 楼层: {floor_level.get('name')}")
    print(f"- 已写入会议室数量: {len(compact_rooms)}")
    print(f"- 配置文件: {conf_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="会议室初始化配置工具")
    parser.add_argument("--page-size", type=int, default=100, help="层级查询分页大小")
    parser.add_argument("--top-n", type=int, default=10, help="城市候选数量（从二级层级截取）")
    args = parser.parse_args()
    run_init(page_size=args.page_size, top_n=args.top_n)


if __name__ == "__main__":
    main()
