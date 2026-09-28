# Bumi 会议纪要助手：短语启动与本地 TXT 导出

0.4.0 使用现有 mic、ASR、Agent Core，加一张独立的 `meeting_minutes_export` MCP 卡片。主持人说“开始会议纪要”即可请求启动，随后再口述主题、参会人和汇报；说“汇报结束，请总结”后，Agent 保存 TXT 草稿到 Bumi 的 `/home/noetix/meeting-minutes/`。每项行动项记录负责人、截止时间、交付物、验收人、验收标准。缺失字段写“待确认”。文件不表示已派单或通知。

## 在 Bumi 安装（先停止画布智能控制）

**真机测试前不要推送会议分支，也不要在 Bumi 上执行无法拉取的 `git pull`。**在电脑的本地会议目录中，先用 SSH/SCP 传这次实际需要的文件（交互式终端自行完成认证，不要在聊天中发送密码或私钥）：

```powershell
cd <本机仓库>\demos\meeting-assistant
ssh noetix@192.168.55.101 'mkdir -p ~/phanthymotus-driver-meeting/demos/meeting-assistant/minutes_export ~/phanthymotus-driver-meeting/demos/meeting-assistant/scripts ~/phanthymotus-driver-meeting/demos/meeting-assistant/tests'
scp SKILL.md README.md Dockerfile.minutes-export compose.minutes-export.yaml noetix@192.168.55.101:~/phanthymotus-driver-meeting/demos/meeting-assistant/
scp minutes_export/__init__.py minutes_export/service.py minutes_export/server.py noetix@192.168.55.101:~/phanthymotus-driver-meeting/demos/meeting-assistant/minutes_export/
scp scripts/install_local_skill.py noetix@192.168.55.101:~/phanthymotus-driver-meeting/demos/meeting-assistant/scripts/
scp tests/test_minutes_export.py tests/test_install_local_skill.py tests/check_container_persistence.py noetix@192.168.55.101:~/phanthymotus-driver-meeting/demos/meeting-assistant/tests/
```

随后在 Bumi 的 SSH 终端运行：

```bash
cd ~/phanthymotus-driver-meeting/demos/meeting-assistant
mkdir -p /home/noetix/meeting-minutes
chmod 700 /home/noetix/meeting-minutes
printf 'MEETING_UID=%s\nMEETING_GID=%s\n' "$(id -u)" "$(id -g)" > .env.minutes-export
docker compose --env-file .env.minutes-export -f compose.minutes-export.yaml up -d --build
curl -fsS http://127.0.0.1:15742/healthz
```

构建默认复用 Bumi 已缓存的 `bj-warehouse.tencentcloudcr.com/phanthy-motus/ros-base:latest`。该容器没有 ROS 依赖、没有网页或下载接口，监听 `127.0.0.1:15742`；仅本机进程可访问，供同机 Agent Core 调用。目录挂载到容器内 `/data`，容器按 noetix 的 UID/GID 写入，因此 SSH 用户可直接读取。容器重启不删除宿主机文件。不要运行本目录旧的 `docker compose up`：那会启动已退役的 `meeting_manager` 服务。

在 Agent Core 的 MCP 管理界面注册名称 `Bumi Meeting Minutes Export`、URL `http://localhost:15742/mcp`。确认其工具列表中出现 `meeting_minutes_export`，再将该卡片放到画布。旧 `meeting_manager` 和 `meeting_audio` 不恢复；独立 `health_check` 保持原状，只在主持人明确要求时调用。

更新同一 slug 的 Skill：

```bash
cd ~/phanthymotus-driver-meeting/demos/meeting-assistant
sudo python3 scripts/install_local_skill.py
```

脚本只改 Agent Core ConfigDB 中 `skills` 一行，保留其他 Skill，并生成原配置备份。版本应显示 0.4.0。列表中的 `active=true` 只是已启用；要在智能控制日志看到 `activate_skill({"slug":"meeting-full-cycle-assistant"})` 的**成功返回**，才能确认本轮激活。Skill 的 `oneLiner` 包含短口令，供激活前的 Agent Core 技能列表提示使用。语音路由能否稳定选择该 Skill 需要真机验证；失败时不能仅靠 Skill 指令宣称已解决。

## 画布与口述流程

```text
Bumi mic → ASR (trigger_mode=vad) → decision_core
remote_message → decision_core  （文字测试与纠正）
decision_core 底部执行器 → meeting_minutes_export
decision_core 底部执行器 → health_check  （可选，仅按要求检查）
```

本版纪要不需要 TTS 和 speaker 连线。若其他用途仍保留 TTS，请避免在会议收听及总结期间调用它。停止智能控制后调整连线、保存，再重新开启。ASR 使用 `vad`，不是 `asr_kws`；对着麦克风说完整短语“开始会议纪要”，观察 ASR 数据流和 `activate_skill` 返回。若平台把短语识别出来却没有发起 `activate_skill`，记录为 Agent Core 语音路由限制，先用 `remote_message` 输入“请激活 meeting-full-cycle-assistant”完成其余演示。

1. 说：“开始会议纪要。”等待日志里 `activate_skill` 成功，确认未调用 `health_check`、TTS，也未自发消息到 `/remote_control/message`。未说主题和人员时应显示“待确认”。
2. 说：“主题是 Bumi 产品演示准备，参会人张三和李四。Bumi 还没检查。”然后口述：“张三在 2026 年 10 月 2 日 18 点北京时间前交付演示检查清单，李四验收；标准是麦克风转写、任务字段和语音播报三项都有测试结果。另需准备演示视频，负责人和验收标准未确定。”
3. 说：“汇报结束，请总结。”检查 `meeting_minutes_export` 的 `save` 调用和返回的绝对路径。若没有成功返回，不得说文件已保存。确认演示视频缺失字段为“待确认”，纪要状态为草稿。
4. 补充或纠正一项内容并要求“保存修订版纪要”；确认出现新文件且旧文件仍在。重复同样草稿应返回已有文件。
5. 在 Bumi SSH 终端查看：`ls -lt /home/noetix/meeting-minutes/`，再用 `cat /home/noetix/meeting-minutes/指定文件名.txt` 核对内容。电脑上执行 `scp noetix@192.168.55.101:/home/noetix/meeting-minutes/指定文件名.txt .` 取回**指定**文件。

可从 SSH 直接测试卡片本身：

```bash
curl -sS http://127.0.0.1:15742/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## 测试、限制和回退

```bash
python3 -m unittest discover -s tests -v
docker compose --env-file .env.minutes-export -f compose.minutes-export.yaml ps
python3 tests/check_container_persistence.py
ls -lt /home/noetix/meeting-minutes/
```

单元测试覆盖 UTF-8 内容、五字段缺失、无效输入、重复保存、修订另存和新服务实例读取同一目录。真机脚本自动写入独立测试草稿、重启导出容器、核对文件内容与幂等返回，通过后删除自己的测试文件；失败时保留文件供排查。真机还需验证麦克风转写、短语激活、TXT 路径及无 TTS 回声/输入话题自触发。本版不保证超长会议上下文完整，不提供后台提醒、自动派单和外部通知。

若需停用新卡片：先停止画布智能控制并移除执行器连线，再运行 `docker compose --env-file .env.minutes-export -f compose.minutes-export.yaml down`。不要加 `-v`；该命令不会删除 `/home/noetix/meeting-minutes/`。旧会议服务及 SQLite 数据仍保留供历史回退；不要误启动它。
