"""
Config Schema — JSON Schema 定义 The Machine 配置格式

所有配置变更必须通过此 schema 校验。
"""

CONFIG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["cameras", "detection", "anomaly"],
    "properties": {
        "cameras": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "name", "rtsp"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
                    "name": {"type": "string", "minLength": 1},
                    "rtsp": {
                        "type": "string",
                        "pattern": "^(rtsp|http)://",
                    },
                    "interval_sec": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 30,
                        "default": 2.0,
                    },
                    "active_hours": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "pattern": "^\\d{2}:\\d{2}$"},
                            "end": {"type": "string", "pattern": "^\\d{2}:\\d{2}$"},
                        },
                        "default": {"start": "00:00", "end": "23:59"},
                    },
                },
                "additionalProperties": False,
            },
        },
        "whitelist": {
            "type": "array",
            "default": [],
            "items": {
                "type": "object",
                "required": ["name", "face_label"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "face_label": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        },
        "detection": {
            "type": "object",
            "required": ["confidence"],
            "properties": {
                "model": {
                    "type": "string",
                    "default": "default",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "interval_sec": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 30,
                    "default": 2.0,
                },
                "target_classes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "default": [0],
                },
            },
            "additionalProperties": False,
        },
        "anomaly": {
            "type": "object",
            "properties": {
                "score_threshold": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.7,
                },
                "cooldown_sec": {
                    "type": "number",
                    "minimum": 0,
                    "default": 300,
                },
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "unknown_person",
                            "off_hours_motion",
                            "prolonged_stay",
                            "motion_detected",
                        ],
                    },
                    "default": ["unknown_person", "off_hours_motion", "motion_detected"],
                },
            },
            "additionalProperties": False,
        },
        "notifier": {
            "type": "object",
            "properties": {
                "quiet_mode": {"type": "boolean", "default": False},
                "dnd_start": {
                    "type": "string",
                    "pattern": "^\\d{2}:\\d{2}$",
                    "default": "23:00",
                },
                "dnd_end": {
                    "type": "string",
                    "pattern": "^\\d{2}:\\d{2}$",
                    "default": "07:00",
                },
            },
            "additionalProperties": False,
        },
        "storage": {
            "type": "object",
            "properties": {
                "evidence_retention_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "default": 7,
                },
                "db_path": {
                    "type": "string",
                    "default": "data/events.db",
                },
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


DEFAULT_CONFIG = {
    "cameras": [],
    "whitelist": [],
    "detection": {
        "model": "default",
        "confidence": 0.5,
        "interval_sec": 2.0,
        "target_classes": [0],
    },
    "anomaly": {
        "score_threshold": 0.7,
        "cooldown_sec": 300,
        "rules": ["unknown_person", "off_hours_motion", "motion_detected"],
    },
    "notifier": {
        "quiet_mode": False,
        "dnd_start": "23:00",
        "dnd_end": "07:00",
    },
    "storage": {
        "evidence_retention_days": 7,
        "db_path": "data/events.db",
    },
}
