# Bumi 会议纪要助手（Skill + 现有音频卡片）

0.2.0 只依赖 mic、asr、tts、speaker，由 Agent 在当前对话中整理关键决策和五字段行动项。remote_message 用于文字汇报、纠正以及播报后手动恢复收听。不需要运行自定义会议服务，不提供文件导出、可靠计时或跨会话任务跟进。

## 更新安装

在 Bumi 执行（先停止画布智能控制）：

```bash
cd ~/phanthymotus-driver-meeting
git pull --ff-only
cd demos/meeting-assistant
sudo python3 scripts/install_local_skill.py
```

无需构建 Docker 镜像。脚本以同一个 slug meeting-full-cycle-assistant 覆盖更新，版本为 0.2.0，显示名为“会议纪要助手”；保留其他技能，并备份原 skills 配置行。刷新技能列表，再通过 remote_message 要求 Agent 先 deactivate_skill、再 activate_skill，标识均为 meeting-full-cycle-assistant。核对日志中加载的新指令：当前对话整理、手动恢复收听、不依赖自定义会议服务。

## 画布调整

停止智能控制后，从本次画布移除 meeting_manager、meeting_audio 及其连线。旧服务代码和数据库保留，不删除数据，不必卸载全局 MCP 服务。

```text
Bumi mic → ASR → decision_core
remote_message → decision_core
decision_core 底部执行器 → ASR
decision_core 底部执行器 → TTS
TTS → Bumi speaker
```

ASR 设为 vad。TTS 无需接入 meeting_audio；Agent 通过工具调用 speak。重新启动画布后检查 TTS 实际输出话题与 speaker 订阅一致，不沿用旧的 /meeting_assistant/announcements/tts。

必须保留可用的 remote_message 入口：总结后 ASR 保持停止，语音“继续收听”此时无法触发 Agent。若平台不允许两条数据线同时连接 decision_core，文字操作时切换到 remote_message；输入“继续收听”并确认恢复成功后再接回 ASR。不要猜 ASR 的麦克风话题或创建重复实例。

## 演示话术

每一步等待 Agent 完成本轮操作，再输入下一步。

1. 通过 remote_message 输入：“请激活 meeting-full-cycle-assistant，开始一次会议纪要演示，主题为产品演示准备，参会人张三和李四。Bumi 未检查，不调用健康检查。我同意开始收听，请关闭自动旁白，汇报期间不要插话。”
2. 口述或文字输入：“我是张三。我们决定先完成演示检查。张三在 2026 年 10 月 2 日 18 点北京时间前交付演示检查清单，李四验收，标准是麦克风转写、任务字段、语音播报三项都有测试结果。另有一项待办是准备演示视频，负责人和验收标准还没有确定。”测试时将截止日期换成合适的未来时间。
3. 输入：“汇报结束，请总结。”检查先停止 ASR，再生成决策、行动项和待确认问题，并由 TTS 播报。第二项不能擅自补齐。
4. 实际播报结束后，通过 remote_message 输入：“继续收听。”核对原 ASR 恢复后再口述补充，或者直接通过文字补充。
5. 输入：“我确认当前纪要。”只能标记对话内容已确认，不能声称已派单、入库或通知人员。

新会话或重启后需要主持人重新提供背景。平台是否展示普通文字回复需现场确认；本版没有独立页面和下载文档。

## 验证与已知阻塞

```bash
python3 -m unittest discover -s tests -v
```

自动测试验证覆盖旧版本、清除旧工具依赖、重复安装、备份与保留其他技能。真机需验证安静收听、ASR 暂停/恢复、纪要字段和实际出声。

此前日志显示 TTS 生成 23 帧音频，bumi_speaker 订阅正确，但 Bumi 未出声；该问题尚未解决。queued 或发布帧数都不能作为实际播报成功的证据。重接画布后仍无声时，保留新的 TTS 输出话题、ROS 订阅信息和 Bumi 播放日志，继续定位运行中的驱动；不要仅为此盲目更换镜像。

旧会议服务仅保留供历史记录和回退使用，数据位置为 /opt/phanthy-motus/data/meeting-assistant/meetings.sqlite3；新版 Skill 不查询或更新它。回退时使用安装脚本生成的 skills 配置备份恢复对应技能，注意保留备份之后新增的其他技能，再重新激活旧技能及恢复旧画布。
