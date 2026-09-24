# Bumi 会议全流程助手（Skill + 画布卡片）

此演示不提供独立任务板页面。`meeting_manager` 卡片负责会议、汇报原文、决策、行动项和验收的本地持久化；`meeting_audio` 卡片发布固定的议程提醒文字；`SKILL.md` 引导 Agent 听取汇报、提炼关键信息并用现有 TTS 口头总结。服务 MCP 地址为 `http://<Bumi-IP>:15740/mcp`，数据保存在 `/opt/phanthy-motus/data/meeting-assistant/meetings.sqlite3`。

## Bumi 画布连接

停止智能控制后调整画布，连接如下：

```text
Bumi mic ──(audio/pcm-16k)──> ASR ──(data/json)──> decision_core
remote_message ──(data/json)──────────────────────> decision_core  （文字备用）
decision_core 底部绿色执行器 ──────────────────────> meeting_manager
decision_core 底部绿色执行器 ──────────────────────> TTS
meeting_audio ──(data/json)──> TTS ──(audio/pcm-16k)──> Bumi speaker
```

原有 `meeting_audio → speaker` 音频连线需删除。`meeting_audio` 现在发布文字提醒，由 TTS 转成音频；TTS 也负责朗读 Agent 的会议总结。Bumi 扬声器一次只订阅一个输入话题，不能用两路音频源同时连接。ASR 卡片的 `trigger_mode` 在主持人控制的汇报时段设为 `vad`，否则唤醒词模式可能忽略普通发言。汇报结束后停止麦克风或 ASR，再让 Agent 口头总结，避免机器人播报被麦克风再次收录。先用一段短汇报测试 ASR 数据流确有文字输出，再测试总结。

ASR 输出只有文字和音频时间戳，不提供可靠的说话人身份；主持人应让每位汇报人自报姓名，未确定的负责人、截止时间、交付物、验收人和验收标准必须标为待确认。只有主持人确认五项字段后，`confirm_task` 才创建正式任务。

## 部署与 Skill 更新

在 Bumi 的本项目目录运行：

```bash
git pull --ff-only
cd demos/meeting-assistant
docker compose up -d --build
sudo python3 scripts/install_local_skill.py
```

安装脚本按 slug 更新 Agent Core 中的 Skill，并在写入前备份原 `skills` 配置行。安装完成后刷新 Agent Core「技能 → 已安装」。如 Agent 仍沿用旧指令，可让它先调用 `deactivate_skill`，再调用 `activate_skill`，slug 均为 `meeting-full-cycle-assistant`。无需 Resource Center 或 PR。

`MEETING_ENABLE_HEALTH_CHECK=0` 为默认值，`check_robot` 会拒绝执行且**不会请求 Bumi 驱动**。只有今后主持人要求健康检查时，才将 `compose.yaml` 中的值改成 `1` 并重建服务。未开始的旧会议可通过 `meeting_manager.cancel_meeting` 标为已取消，记录保留；`end_meeting` 只适用于已开始的会议。

## 演示

主持人通过 Bumi 麦克风说出会议汇报，或用 `remote_message` 输入文字。Agent 把原话存为 `record_report`，明确决策存为 `record_decision`，行动项存为 `record_draft`。要求总结时，它调用 `brief` 获取已保存内容和缺失字段，再调用 `tts.speak` 读出“谁在何时完成什么、交付什么、由谁按什么标准验收”。不确定的字段说“待确认”，草稿不能说成已派发。负责人提交证据后由验收人审核。

构建使用 Bumi 已有的 `bj-warehouse.tencentcloudcr.com/phanthy-motus/ros-base:latest` 镜像，不运行 `apt-get`。运行本地回归测试：`python -m unittest discover -s tests -v`。
