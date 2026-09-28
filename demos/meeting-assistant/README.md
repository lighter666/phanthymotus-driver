# Bumi 会议纪要助手（Skill + 独立健康检查卡片）

0.3.0 通过独立 `health_check` 卡片做会前 Bumi 检查，通过文字或现有 mic、asr 收集汇报，由 Agent 在当前对话中整理关键决策和五字段行动项。remote_message 用于文字汇报、纠正和确认。不需要运行自定义会议服务，不提供文件导出、可靠计时或跨会话任务跟进。当前平台不向 Agent 暴露 ASR 的 `stop`，因此 ASR 运行时只做文字纪要，不自动播报。

## 更新安装

在 Bumi 执行（先停止画布智能控制）：

```bash
cd ~/phanthymotus-driver-meeting
git pull --ff-only
cd demos/meeting-assistant
sudo python3 scripts/install_local_skill.py
```

无需构建会议 Docker 镜像。脚本以同一个 slug meeting-full-cycle-assistant 覆盖更新，版本为 0.3.0，显示名为“会议纪要助手”；保留其他技能，并备份原 skills 配置行。刷新技能列表，再通过 remote_message 要求 Agent 先 deactivate_skill、再 activate_skill，标识均为 meeting-full-cycle-assistant。核对日志中加载的新指令：按需调用 health_check、五字段纪要、ASR 未确认停止时只做文字总结。

## 画布调整

停止智能控制后，先停止旧会议服务，再注销它在 Agent Core 中注册的 MCP。只处理旧会议服务，不影响独立的 `health_check` 服务及 Bumi 驱动：

```bash
cd ~/phanthymotus-driver-meeting/demos/meeting-assistant
docker compose down
python3 scripts/remove_legacy_cards.py
python3 scripts/remove_legacy_cards.py --apply
```

脚本只匹配名称为 `Bumi Meeting Assistant` 且 URL 为 `http://localhost:15740/mcp` 的注册项；第一遍只预览。`docker compose down` 不加 `-v`，脚本也不碰旧会议数据库。然后从当前画布删除 `meeting_manager`、`meeting_audio` 两个节点及连线，保存画布并刷新页面。仅删除画布节点不会注销工具列表里的旧卡片。旧服务代码和数据库保留供回退。

```text
Bumi mic → ASR → decision_core
remote_message → decision_core
decision_core 底部执行器 → ASR
decision_core 底部执行器 → TTS
decision_core 底部执行器 → health_check
TTS → Bumi speaker
```

ASR 设为 vad。独立 `health_check` 必须先部署并在 Agent Core 中注册；其画布卡片经执行器绿线连到 decision_core 后，Agent 才能用 `action: check` 调用。若卡片不可用，Skill 记录“未检查”。TTS 无需接入 meeting_audio；重新启动画布后检查 TTS 实际输出话题与 speaker 订阅一致，不沿用旧的 /meeting_assistant/announcements/tts。绿色画布连线本身不证明 Agent 可以调用 ASR 的 `stop`：2026-09-28 真机直接查询 Perception MCP，确认 `asr` 含有 `start/stop/info/config`；但 Agent Core 的 `mcp_client.all_schemas()` 会过滤 processor 的这些系统 action，所以 ASR 在 LLM 工具列表中完全消失，TTS 则因有 `speak` 而可见。0.3.0 要求 ASR 未确认停止时只给文字纪要，禁止播报，也不得声称 ASR 已停止。要让 Agent 自动暂停 ASR 再播报，需要平台新增受控的 ASR 生命周期接口，不能仅靠 Skill 或绿色连线完成。

必须保留可用的 remote_message 入口供文字汇报、要求检查、纠正和确认。当前版本不能由 Agent 自动停止 ASR，文字总结后不得声称它已停止或需要恢复。若平台不允许两条数据线同时连接 decision_core，文字测试时切换到 remote_message；不要猜 ASR 的麦克风话题或创建重复实例。

## 演示话术

每一步等待 Agent 完成本轮操作，再输入下一步。

1. 通过 remote_message 输入：“请激活 meeting-full-cycle-assistant，开始一次会议纪要演示，主题为产品演示准备，参会人张三和李四。请调用独立 health_check 卡片做一次会前检查，报告总体状态、检查时间、关键读数、异常或数据不足原因、未判定项。投影和网络待人工确认。只做文字纪要，不调用 TTS。”
2. 口述或文字输入：“我是张三。我们决定先完成演示检查。张三在 2026 年 10 月 2 日 18 点北京时间前交付演示检查清单，李四验收，标准是麦克风转写、任务字段、语音播报三项都有测试结果。另有一项待办是准备演示视频，负责人和验收标准还没有确定。”测试时将截止日期换成合适的未来时间。
3. 输入：“汇报结束，请只用文字总结，不调用 TTS。”检查决策、行动项、待确认问题和本次 Bumi 健康检查结果；第二项缺失字段不能擅自补齐。ASR 未确认停止时不得播报。
4. 通过 remote_message 补充或纠正缺失字段，再要求更新文字纪要；若仍在语音收听模式，需现场确认 ASR 仍可收到内容，不假设它已停止或恢复。
5. 输入：“我确认当前纪要。”只能标记对话内容已确认，不能声称已派单、入库或通知人员。

新会话或重启后需要主持人重新提供背景。平台是否展示普通文字回复需现场确认；本版没有独立页面和下载文档。

## 验证与已知阻塞

```bash
python3 -m unittest discover -s tests -v
```

自动测试验证覆盖旧版本、清除旧会议工具依赖、重复安装、备份与保留其他技能。真机需验证独立 health_check 调用、状态如实记录、文字纪要字段和 ASR 语音输入。ASR 自动暂停/恢复与实际出声尚未通过验收。

此前日志显示 TTS 生成 23 帧音频，bumi_speaker 订阅正确，但 Bumi 未出声；该问题尚未解决。queued 或发布帧数都不能作为实际播报成功的证据。重接画布后仍无声时，保留新的 TTS 输出话题、ROS 订阅信息和 Bumi 播放日志，继续定位运行中的驱动；不要仅为此盲目更换镜像。

旧会议服务仅保留供历史记录和回退使用，数据位置为 /opt/phanthy-motus/data/meeting-assistant/meetings.sqlite3；新版 Skill 不查询或更新它。回退时使用安装脚本生成的 skills 配置备份恢复对应技能，注意保留备份之后新增的其他技能，再重新激活旧技能及恢复旧画布。
