# Bumi 办公物品借还助手

此 Skill 引导员工自行办理借用或归还：先核验公司员工身份，再询问业务类型与物品，实时读取资产标签，完整播报并等待确认，最后逐件生成记录。当前环境不支持拍照，本流程不调用拍照卡片。它不会凭空建立台账；只有环境实际提供保存机制且返回成功，才播报“登记完成”。

## 画布与运行前提

- 启用 `face_recognition`、`tts`、`ocr`。人脸卡片须已接入实时摄像头，并使用公司的已登记员工人脸库。`recognize_by_stream` 是本流程唯一的人脸识别动作；`recognize`、`recognize_by_photo`、`recognize_by_url` 均不用于本流程。
- 相机输出 `/remote_control/camera` 接入 OCR。调用 `ocr(action="start", input_topic="/remote_control/camera")`，其输出为 `/remote_control/camera/ocr`。必须让当前运行环境能**接收并读取该输出话题的实际新消息**；仅把 OCR 卡片连在画布上、调用 `start` 或查询 `info`，不能保证决策核心读到标签文字。若环境没有话题消息接收能力，Skill 会暂停登记，需要先由部署方打通消息接收链路。
- 语音提示由 `tts(action="speak", text="...")` 执行。保留员工答复进入决策核心的输入链路。若要完成自动登记，还需环境实际提供可调用的记录保存机制和成功回执；没有时输出待保存的结构化记录。
- 每件标签应能清晰显示资产名称、SN 号、资产编号。缺任何一项时继续引导调整，不把口述或 `start` 回执当 OCR 结果。历史借用记录仅在环境实际提供时关联。

卡片接口参考：[人脸识别源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/face.py)、[OCR 源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/ocr.py)、[TTS 源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/tts.py)。

## 交互顺序

1. Bumi 先播报“请面向摄像头”，调用 `face_recognition(action="recognize_by_stream")`。仅单人、清晰且返回已登记姓名和人脸库 ID 时通过；`p-21` 仅在播报时称“陈臻”，记录仍保留原始返回。明确不在员工库就播报警告并停止；无脸、多人、模糊或失败则引导调整重试。
2. 员工未说明业务类型时，询问借用或归还；然后按类型询问要办理什么物品。已有明确答复不重复问。
3. 请员工展示资产标签，准备好后读取 `/remote_control/camera/ocr` **本件展示后的新结果**。从真实消息提取名称、SN 号、资产编号；读不清时引导调整并读新消息。拿错物品时先解决描述与标签的冲突。
4. 冻结三项识别值，完整播报并等员工明确确认。员工指出错误时重新展示、重新读取、重新完整播报；不得仅按口述修改。仅停止本流程启动的 OCR，不中断共享服务。
5. 逐件生成结构化记录。归还时若有原借用记录，按资产编号和 SN 号双字段关联；无记录要标明无法核对借出基线。实际保存成功才播报完成；无保存机制时播报“记录已生成，等待保存”。多件物品每件清空上一件的 OCR 候选值。

## 安装与检查

将本目录复制到 Bumi 主机，在目录内运行：

```bash
python3 scripts/install_local_skill.py
python3 scripts/install_local_skill.py --check
```

脚本默认操作 `/opt/phanthy-motus/data/data.db` 的 `config.skills`：变更前备份旧值、按同一 `slug` 新增或更新、保留其他 Skill，写后重新读取核对。数据库不在默认位置时加 `--db /实际路径/data.db`。检查应显示 `版本=3.0.0`、`与本目录 SKILL.md 一致：是`。刷新 Skill 列表并重新激活；推送 GitHub 分支不会自动修改 Bumi 数据库。

## 验收

| 场景 | 应看到的行为 |
| --- | --- |
| 正常借用/归还 | 人脸 → 类型 → 物品 → 新 OCR 消息 → 三项完整播报/确认 → 逐件记录；仅保存成功后说“登记完成” |
| `p-21` | 播报“陈臻”，记录保留真实人脸返回姓名与 `person_id` |
| 明确不在库 | 播报警告并停止，不生成完成记录 |
| 无脸、多人、模糊或人脸调用失败 | 引导重试，不误判为不在库，不接受口述姓名替代 |
| OCR 无接收链路、无新消息或字段不全 | 暂停登记；`start`/`info` 回执不当作标签文字 |
| 员工否认 OCR、拿错物品 | 新展示、新消息、重新完整播报；未消除差异不记相符 |
| 归还无原记录或字段不符 | 标注缺少基线或逐项差异，不自动认定正常归还 |
| 无保存机制、保存失败、取消 | 分别写等待保存、保存失败、当前件中止；都不宣布登记完成 |
| 多件物品与重复安装 | 每件只用各自的新 OCR 结果；同一 `slug` 仅一项且其他 Skill 不变 |

本地安装测试：`python3 -m unittest discover -s tests -v`。这些测试不能代替 Bumi 实机上的话题消息、人脸库、TTS 与保存回执验收。
