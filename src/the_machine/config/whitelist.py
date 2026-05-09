"""白名单管理器 — 管理已知人员列表，支持增删改查"""
import json
from pathlib import Path
from typing import Optional


class WhitelistManager:
    """白名单管理器 — 人员的增删改查"""

    def __init__(self, config_manager):
        self._config = config_manager

    def list(self) -> list[dict]:
        """获取白名单列表"""
        return self._config.get("whitelist", [])

    def add(self, name: str, face_label: str) -> bool:
        """新增白名单人员，已存在时更新 face_label"""
        whitelist = self._config.get("whitelist", [])
        for person in whitelist:
            if person["name"] == name:
                person["face_label"] = face_label
                self._config.update("whitelist", whitelist)
                return True  # 已存在，更新
        whitelist.append({"name": name, "face_label": face_label})
        self._config.update("whitelist", whitelist)
        return True

    def remove(self, name: str) -> bool:
        """从白名单移除人员"""
        whitelist = self._config.get("whitelist", [])
        new_list = [p for p in whitelist if p["name"] != name]
        if len(new_list) == len(whitelist):
            return False  # 未找到
        self._config.update("whitelist", new_list)
        return True

    def is_known(self, face_label: str) -> Optional[str]:
        """查询 face_label 是否在白名单中，返回对应名称"""
        for person in self._config.get("whitelist", []):
            if person["face_label"] == face_label:
                return person["name"]
        return None

    def __len__(self) -> int:
        return len(self._config.get("whitelist", []))
