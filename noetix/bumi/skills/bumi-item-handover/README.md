# Bumi 办公物品借还自助核验

Bumi 每次只提示借还人完成**当前一步**，等回答或工具结果返回后再继续：确认借出/归还与基线 → 人脸核对 → OCR 读取资产标签 → 逐件确认配件与外观 → 拍照 → 确认取走/放回 → 输出摘要。全过程直接面向借还人，不询问管理员。

本版不使用 VOP。Bumi 可以通过 OCR 比对清晰可见的资产编号，但不能自动识别主设备类别、无标签配件或设备功能。物品名称、配件、外观由借还人逐项确认，并在摘要中标明来源。识别不一致时，Bumi 复核一次，再询问借还人是否确认差异并仍要继续；答“确认”也保留差异，不会变成核对相符。此 Skill 不查询跨会话台账，也不代表正式借还登记或保管方实际接收。

## 画布连接

- 需要 Bumi 的 `camera`、`vision_capture` 和感知卡片 `face_recognition`、`ocr`。从 Bumi `camera` 的图像输出分别连到人脸卡片与 OCR 卡片；把两张卡片的结果分别连到 `decision_core` 感知输入。
- 从 `decision_core` 底部执行器端口分别连到 `face_recognition`、`ocr`、`vision_capture`，以便按需调用动作。保留 `remote_message → decision_core` 的文字输入。`vision_capture` 使用 Bumi 驱动内部相机，无需从其他卡片接图像。
- 旧画布上的 VOP 卡片及其连线可移除；本 Skill 的 `requiredTools` 已不包含 `vop`。若其他流程仍用 VOP，只需确保它不参与本次借还流程。
- 人脸库应事先经本人同意录入真实姓名。录入使用 `register_by_photo`；本 Skill 只使用只读的 `recognize_by_stream`，不会自动注册人员。[人脸卡片说明](https://github.com/4paradigm/phanthymotus/blob/main/perception/README.md)
- OCR 使用实时相机结果中的 `text`、`items`、`timestamp`。不要直接把 `vision_capture` 返回的本机照片路径传给 OCR 的 `recognize_by_photo`；感知服务与 Agent Core 可能不共享文件系统。[OCR 卡片源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/ocr.py)

## 安装与检查

将本目录复制到 Bumi 主机，在目录内运行：

```bash
python3 scripts/install_local_skill.py
python3 scripts/install_local_skill.py --check
```

脚本默认更新 `/opt/phanthy-motus/data/data.db` 的 `config.skills`；路径不同可用 `--db /实际路径/data.db`。安装前会备份原 `skills` 配置，并按 `slug` 更新，不更改其他 Skill。`--check` 只读核对数据库，期望显示 `版本=2.1.0`、`与本目录 SKILL.md 一致：是`、`包含旧版管理员提问：否`、`其他激活的管理员版借还 Skill：无`。

刷新 Skill 列表，停用旧版本、激活当前 `bumi-item-handover`，在**新对话**中测试。只把本目录的 `SKILL.md` 安装到 Bumi；GitHub 分支更新不会自动更新 Bumi 数据库。若检查通过却仍听到旧话术，还需检查画布提示词或其他激活的 Skill。

## 借还人体验

开场只需说“我要借出物品”或“我要归还物品”。Bumi 将按顺序提示：

| 步骤 | Bumi 的一句提示示例 | 等待的输入 |
| --- | --- | --- |
| 基线 | “请说物品名称。”随后单独询问资产编号、配件、预计归还时间或原记录 | 每个字段一次回答 |
| 人员 | “请说你的姓名。”随后询问人脸识别同意，再提示单人面向相机 | 姓名、同意、准备完成 |
| 标签 | “请把资产标签正对相机，准备好后说完成。” | 新 OCR 结果 |
| 配件 | “请展示电源适配器，回答有、缺少或不确定。” | 逐件回答 |
| 外观 | “外观有划痕或破损吗？” | 具体说明或“没有” |
| 照片 | “请摆好物品和配件，准备好后说拍照。” | 拍照指令及保存回执 |
| 交接 | “你已经取走/放回物品了吗？” | 明确回答，然后输出摘要 |

借还人可随时说“重试”“跳过”“取消”。如果 Bumi 提示姓名或编号冲突，应先重试识别；仍冲突时借还人可以明确确认差异并要求继续留证，摘要仍标记异常。归还时应提供原借出摘要或记录，缺少基线不能报告正常归还。照片默认保存在 `/opt/phanthy-motus/data/vision_capture/photos/`，以卡片返回的实际路径为准；保存回执不证明原图清晰。

## 验收

| 场景 | 预期结果 |
| --- | --- |
| 正常借出、归还 | 一次只提示一个动作，逐步等待回答；摘要分开标明机器结果和借还人确认 |
| 已给出部分信息 | 不重复询问已知字段，仍按顺序指导展示和拍照 |
| 人脸未知、多人或姓名冲突 | 重试一次；仍不符则询问是否确认差异继续，不能改写为身份相符 |
| OCR 标签不清或编号不符 | 调整后重试；仍不符则标记未验证或冲突 |
| 无 VOP | 流程正常；不输出机器识别的物品类别或配件结论 |
| 少还配件或外观变化 | 逐项记录借还人回答，与原记录冲突时保留差异 |
| 无原借出记录 | 可继续留证，但不得声称正常归还 |
| 拍照失败、中止 | 不宣称留证完成；停止未发生的步骤，保留已发生事实 |
| 重复安装 | 同一 `slug` 仅一项；其他 Skill 保留，配置不变时不再备份 |

本地安装测试：

```bash
python3 -m unittest discover -s tests -v
```

自动测试不能代替 Bumi 实机的相机、OCR、人脸和拍照流程验收。
