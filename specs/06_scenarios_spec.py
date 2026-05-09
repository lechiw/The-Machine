"""
Spec: 端到端场景规约（故事情节验收）

这些是高阶验收场景，模拟真实使用情况。
每个场景可以拆分为多个单元测试，但这里作为集成测试的定义。
"""

import pytest


class TestScenarioUnknownPerson:
    """场景 1：陌生人出现在门口"""

    """
    故事：
    老大在家，门口摄像头检测到一个不在白名单中的人出现。
    持续了 15 秒后离开。

    预期行为：
    1. ✅ 摄像头成功拉取帧
    2. ✅ YOLO 检测到人（class 0）
    3. ✅ FaceNet 无法匹配白名单 → unknown
    4. ✅ Analyzer 触发 unknown_person 规则
    5. ✅ 异常评分 ≥ 阈值
    6. ✅ QQ 收到告警：🚨 Number #1 | 门口 | 检测到未知人员
    7. ✅ 告警附带截图
    8. ✅ 冷却期 5 分钟内不重复发同类告警
    """

    def test_full_flow(self, the_machine, simulated_scenario):
        result = the_machine.run_scenario(simulated_scenario('unknown_person_at_door'))
        assert result['alert_generated'] is True
        assert result['alert']['event_type'] == 'unknown_person'
        assert result['alert']['camera_id'] == 'front_door'
        assert result['alert']['sent_to_qq'] is True
        assert result['alert']['has_evidence'] is True


class TestScenarioOffHours:
    """场景 2：凌晨 3 点，门口有动静"""

    """
    故事：
    凌晨 3 点，无人应活动的时段，门口检测到移动目标。

    预期行为：
    1. ✅ Analyzer 检查 off_hours_motion 规则
    2. ✅ 当前时间在 active_hours 之外
    3. ✅ 触发告警
    4. ✅ 如果开启了免打扰，消息缓存到早上 7 点
    5. ✅ 如果未开启免打扰，立即推送
    """

    def test_off_hours_alert(self, the_machine, simulated_scenario):
        result = the_machine.run_scenario(simulated_scenario('off_hours_motion'))
        assert result['alert_generated'] is True
        assert result['alert']['event_type'] == 'off_hours_motion'


class TestScenarioNormalActivity:
    """场景 3：正常工作日下午"""

    """
    故事：
    下午 3 点，老大在家正常活动，频繁经过摄像头区域。

    预期行为：
    1. ✅ 检测到人（class 0）
    2. ✅ FaceNet 识别为 known（老大）
    3. ✅ 所有规则无触发
    4. ✅ 无告警
    5. ✅ 数据被记录用于基线更新
    """

    def test_no_alert_for_known_person(self, the_machine, simulated_scenario):
        result = the_machine.run_scenario(simulated_scenario('normal_known_activity'))
        assert result['alert_generated'] is False
        assert len(result['detections']) > 0, "应有检测记录"
        assert result['baseline_updated'] is True, "基线应更新"


class TestScenarioProlongedStay:
    """场景 4：门口有人长时间停留"""

    """
    故事：
    门口检测到同一个人停留超过 5 分钟。

    预期行为：
    1. ✅ 最初按 unknown_person 触发告警
    2. ✅ 持续检测到该人 → prolonged_stay 触发
    3. ✅ 冷却期内不重复相同类型告警
    """

    def test_prolonged_stay_triggers(self, the_machine, simulated_scenario):
        result = the_machine.run_scenario(simulated_scenario('prolonged_stay_10min'))
        assert result['alert_generated'] is True
        assert 'prolonged_stay' in result['triggered_rules']


class TestScenarioMultipleCameras:
    """场景 5：多摄像头同时运行"""

    """
    故事：
    同时接入门口、后院、车库三个摄像头。

    预期行为：
    1. ✅ 三个摄像头独立并行拉流
    2. ✅ 每个摄像头独立检测和评分
    3. ✅ 告警按摄像头分别管理冷却期
    4. ✅ 无摄像头之间串扰
    """

    def test_multi_camera_independence(self, the_machine, simulated_scenario):
        result = the_machine.run_scenario(simulated_scenario('three_cameras_active'))
        assert result['cameras_active'] == 3
        events = result['events']
        camera_ids = {e['camera_id'] for e in events}
        assert len(camera_ids) == 3, "三个摄像头都应产出事件"


class TestScenarioRecovery:
    """场景 6：摄像头断流恢复"""

    """
    故事：
    门口摄像头 RTSP 流中断 30 秒后自动恢复。

    预期行为：
    1. ✅ Camera 检测到断流
    2. ✅ 自动重连（最多 3 次尝试）
    3. ✅ 重连成功后继续正常检测
    4. ✅ 断流期间无帧产出但服务不崩溃
    5. ✅ 恢复后日志记录重连耗时
    """

    def test_camera_recovery(self, the_machine, simulated_scenario):
        result = the_machine.run_scenario(simulated_scenario('camera_disconnect_30s'))
        assert result['recovered'] is True
        assert result['downtime_seconds'] < 60, "应在 60s 内恢复"
        assert result['frames_before'] > 0
        assert result['frames_after'] > 0


class TestScenarioConfigChange:
    """场景 7：运行时修改配置"""

    """
    故事：
    系统运行时，老大通过 QQ 修改配置：
    "把置信度调到 0.8"
    "门口设为安静模式"

    预期行为：
    1. ✅ 配置热重载生效
    2. ✅ 置信度调高后过滤掉低质量检测
    3. ✅ 安静模式下不推送告警
    4. ✅ 服务不中断
    """

    def test_config_change_during_runtime(self, the_machine, simulated_scenario):
        pre_state = the_machine.get_state()
        result = the_machine.run_scenario(simulated_scenario('runtime_config_change'))
        assert result['reloaded'] is True
        assert result['confidence'] == 0.8
        assert result['front_door_quiet'] is True
        post_state = the_machine.get_state()
        assert post_state['uptime_seconds'] >= pre_state['uptime_seconds'], "不应重启"


class TestScenarioErrors:
    """场景 8：异常输入处理"""

    def test_invalid_rtsp_url_handled(self, the_machine):
        """无效 RTSP URL 应记录错误但不崩溃"""
        result = the_machine.add_camera("bad_cam", "rtsp://invalid-url")
        assert result['success'] is False
        assert result['error'] is not None
        # 系统仍在运行
        assert the_machine.is_alive() is True

    def test_config_file_missing(self, the_machine):
        """配置文件缺失应 fallback 到默认配置"""
        result = the_machine.load_config("/nonexistent/path.json")
        assert result['fallback'] is True
        assert result['config'] is not None, "应使用默认配置"
