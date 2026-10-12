# Bumi 办公物品借还助手

此 Skill 先确定借用或归还，再只执行对应的一套逐步提示。Bumi 每次只告诉员工**当前要做什么**，等到明确答复或真实卡片结果才进入下一步。当前环境不支持拍照，本流程不调用拍照卡片。只有环境实际提供保存机制且返回成功，才播报“登记完成”。

## 画布与运行前提

- 启用 `face_recognition`、`tts`、`ocr`。人脸卡片须已接入实时摄像头，并使用公司的已登记员工人脸库。`recognize_by_stream` 是本流程唯一的人脸识别动作；`recognize`、`recognize_by_photo`、`recognize_by_url` 均不用于本流程。
- 相机输出 `/remote_control/camera` 接入 OCR。调用 `ocr(action="start", input_topic="/remote_control/camera")`，其输出为 `/remote_control/camera/ocr`。必须让当前运行环境能**接收并读取该输出话题的实际新消息**；仅把 OCR 卡片连在画布上、调用 `start` 或查询 `info`，不能保证决策核心读到标签文字。若环境没有话题消息接收能力，Skill 会暂停登记，需要先由部署方打通消息接收链路。
- 语音提示由 `tts(action="speak", text="...")` 执行。保留员工答复进入决策核心的输入链路。若要完成自动登记，还需环境实际提供可调用的记录保存机制和成功回执；没有时输出待保存的结构化记录。
- 每件标签应能清晰显示资产名称、SN 号、资产编号。缺任何一项时继续引导调整，不把口述或 `start` 回执当 OCR 结果。历史借用记录仅在环境实际提供时关联。

卡片接口参考：[人脸识别源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/face.py)、[OCR 源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/ocr.py)、[TTS 源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/tts.py)。

## 借用：逐步引导

1. 问“您要借用什么物品？”，等待回答。
2. 请借用人把资产标签对准摄像头，等他说准备好，再读取 `/remote_control/camera/ocr` **本次展示后的新消息**。
3. 完整播报资产名称、SN 号、资产编号，等待三项均明确确认；有错就重新展示、重新读取和播报。
4. 一次询问并逐项记录随借配件的名称、数量和状态；含糊或有差异时留在这一步清点。
5. 请借用人单独面向摄像头，调用 `face_recognition(action="recognize_by_stream")` 核验公司员工身份。
6. 生成本件借用记录，实际保存成功才播报完成；然后才问是否还有下一件。

## 归还：逐步引导

1. 请归还人单独面向摄像头，先调用 `face_recognition(action="recognize_by_stream")` 核验身份。
2. 问“您要归还什么物品？”，等待回答。
3. 请归还人展示资产标签，等准备好后读取本次新 OCR 消息。
4. 完整播报资产名称、SN 号、资产编号，等待三项均明确确认；有错就在这一步重新识别。
5. 询问全部归还配件并逐项记录；有原借用记录时按资产编号、SN 号和配件清单比对，没有则标明缺少借用基线。
6. 生成本件归还记录，保留差异状态；实际保存成功才播报完成，然后才问是否还有下一件。

两条流程都不接受口述姓名替代人脸核验，也不把 OCR 的 `start` 或 `info` 回执当成标签文字。`p-21` 仅在播报时称“陈臻”，记录保留人脸卡片原始返回。没有保存机制时输出完整的待保存记录并播报“记录已生成，等待保存”。每件重新清空标签和配件候选值；仅停止本流程启动的 OCR，不中断共享服务。

## 安装与检查

将本目录复制到 Bumi 主机，在目录内运行：

```bash
python3 scripts/install_local_skill.py
python3 scripts/install_local_skill.py --check
```

脚本默认操作 `/opt/phanthy-motus/data/data.db` 的 `config.skills`：变更前备份旧值、按同一 `slug` 新增或更新、保留其他 Skill，写后重新读取核对。数据库不在默认位置时加 `--db /实际路径/data.db`。检查应显示 `版本=3.2.0`、`与本目录 SKILL.md 一致：是`。刷新 Skill 列表并重新激活；推送 GitHub 分支不会自动修改 Bumi 数据库。

## 验收

| 场景 | 应看到的行为 |
| --- | --- |
| 正常借用 | 类型 → 物品 → 新 OCR 消息 → 三项完整播报/确认 → 配件逐项陈述 → 人脸 → 逐件记录；每步等答复才前进 |
| 正常归还 | 类型 → 人脸 → 物品 → 新 OCR 消息 → 三项完整播报/确认 → 配件逐项核对 → 逐件记录；每步等答复才前进 |
| `p-21` | 播报“陈臻”，记录保留真实人脸返回姓名与 `person_id` |
| 明确不在库 | 播报警告并停止，不生成完成记录 |
| 无脸、多人、模糊或人脸调用失败 | 引导重试，不误判为不在库，不接受口述姓名替代 |
| OCR 无接收链路、无新消息或字段不全 | 暂停登记；`start`/`info` 回执不当作标签文字 |
| 员工否认 OCR、拿错物品 | 新展示、新消息、重新完整播报；未消除差异不记相符 |
| 归还无原记录或字段不符 | 标注缺少基线或逐项差异，不自动认定正常归还 |
| 无保存机制、保存失败、取消 | 分别写等待保存、保存失败、当前件中止；都不宣布登记完成 |
| 多件物品与重复安装 | 每件只用各自的新 OCR 结果；同一 `slug` 仅一项且其他 Skill 不变 |

本地安装测试：`python3 -m unittest discover -s tests -v`。这些测试不能代替 Bumi 实机上的话题消息、人脸库、TTS 与保存回执验收。
