# Bumi 会议全流程助手（演示版）

独立 MCP 服务，提供 `meeting_manager` 和 `meeting_audio` 两张卡片；`SKILL.md` 是会议流程说明。不会修改 Bumi 现有驱动。

## 本机试用

Windows PowerShell：

```powershell
$env:MEETING_ROS='0'
$env:REGISTER_AGENT_CORE='0'
$env:MEETING_DB=(Join-Path (Get-Location) 'demo.sqlite3')
python -m meeting_assistant.server
```

打开 `http://localhost:15740/`。没有 ROS2 和 Bumi 时，会议、计时、任务、验收仍可试用；Bumi 健康检查和播报会明确显示不可用。

可选：先在另一个终端以相同 `MEETING_DB` 运行 `python -m scripts.seed_demo`，生成一场示例会议和两条尚未派发的行动项草稿。

## 真机演示

将项目复制到 Bumi 板载计算机后，在项目目录运行 `docker compose up -d --build`。任务板地址为 `http://192.168.55.101:15740/`，MCP 地址为 `http://192.168.55.101:15740/mcp`。服务会注册到本机 Agent Core。确认画布上有 `meeting_manager`、`meeting_audio`，把 `meeting_audio` 的 `audio/pcm-16k` 输出接到现有 Bumi `speaker` 输入，再启动两张卡片。Bumi 原有 `health_check` 需要已部署且启用。

### 离线安装会议 Skill

Agent Core 的 Skill 界面不能直接上传本地 `SKILL.md`。若不使用 Resource Center，可在 Bumi 的本项目目录运行：

```bash
sudo python3 scripts/install_local_skill.py
```

脚本只修改 `/opt/phanthy-motus/data/data.db` 的 `skills` 配置行，保留其他技能，重复运行按 slug 更新；写入前将原配置备份为同目录的 `skills-row-backup-*.json`。完成后刷新 Agent Core 的「技能 → 已安装」页面，应看到「会议全流程助手」处于激活状态。此处的激活使 Skill 对 Agent 可见；Agent 在实际使用时还需调用 `activate_skill` 加载完整指令。无需提交 Resource Center 审核或创建 PR。

基础镜像默认使用 `bj-warehouse.tencentcloudcr.com/phanthy-motus/ros-base:latest`，Bumi 已有该镜像时无需重新下载。镜像构建直接复制仓库内的提示音文件，不运行 `apt-get`，可在 Bumi 无法访问软件源时构建。

`MEETING_DB` 默认保存在宿主机 `/opt/phanthy-motus/data/meeting-assistant/meetings.sqlite3`，容器替换后数据仍在。`MEETING_PORT` 默认 15740，`BUMI_MCP_URL` 默认 `http://localhost:15704/mcp`，`AGENT_CORE_URL` 默认 `https://localhost:15678`；仅对本机 HTTPS 注册连接兼容 Agent Core 的自签名证书。

仓库内的 `assets/five_minutes.wav` 与 `assets/time_up.wav` 是预制的中文语音，格式为单声道 PCM16、16 kHz，部署后需试听确认。`scripts/generate_prompts.sh` 仅供有 `espeak-ng`、`ffmpeg` 的开发机重新生成素材，镜像构建不会运行它。会议服务在每项议程剩余五分钟、到时各发布一次，短于五分钟的议程只播报到时。页面会显示发送失败；“已发布”仅表示音频提交给 ROS，不等于已证实扬声器发声。

## 演示路径

创建会议 → 确认人员和投影/网络 → 检查 Bumi → 开始会议 → 记录决策和两条行动项草稿 → 结束会议 → 主持人补齐任务字段并确认 → 负责人提交说明 → 验收人通过或退回。正式任务要求负责人、截止时间、交付物、验收人、验收标准；草稿不自动派发。任务板仅按输入的姓名限制操作，**没有账号认证**，仅供受控演示环境使用。

运行测试：`python -m unittest discover -s tests -v`。
