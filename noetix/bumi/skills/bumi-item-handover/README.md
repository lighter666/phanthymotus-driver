# Bumi 办公物品借还现场核验

此 Skill 用 Bumi 相机和现有 `face_recognition` 卡片识别借用人候选，用 `ocr` 读取可见资产标签文字、`vop` 辅助识别物品类别，再用 `vision_capture` 拍摄借还交接现场。管理员确认人脸候选、资产编号和配件核对结果，检查实物与原图，最后把交接摘要录入正式台账。Skill 不维护借还数据库，也不自动解码二维码。

## 前置条件

- Bumi 的 PhanthyMotus 画布上已提供 `vision_capture` 工具；在卡片上执行 `start` 应返回 `state=ready`。其 `capture_photo` 成功时返回 `ok=true`、`file_path` 和 `captured_at`。
- 画布上有 Bumi 的 `camera` 卡片，以及感知服务的 `face_recognition`、`ocr`、`vop` 卡片。人脸卡片支持 `recognize_by_stream`，且预先录入了要识别的员工。未注册或未命名的人脸不能自动当作借用人。
- `ocr` 和 `vop` 已加载各自模型，能够接收同一 Bumi 相机的新画面。`vop` 仅支持模型内固定的类别；部署前在卡片执行 `list_recognizable_objects`，确认目标物品类别是否在列表中。
- 操作者可以在 Bumi 主机打开照片。默认目录为 `/opt/phanthy-motus/data/vision_capture/photos/`，实际以卡片返回的路径为准。
- 管理员在场，拥有原借出记录或借出时的配件清单，负责实物交接和正式台账登记。

## 画布连接与卡片准备

停止智能控制后，从 Bumi `camera` 的图像输出分别连到 `face_recognition`、`ocr`、`vop` 的图像输入；再把这三个卡片的结果输出分别连到 `decision_core` 的感知输入。`decision_core` 底部执行器端口分别连接 `face_recognition`、`ocr`、`vop` 与 `vision_capture`，以便按需调用卡片动作。保留现有 `remote_message → decision_core` 作为文字输入。使用 Bumi 的 `camera`，不要把 Agent Core 的 `remote_camera` 当成机器人相机。`vision_capture` 复用 Bumi 驱动内部相机画面，无需从其他卡片接收图像数据。

OCR 与 VOP 使用**实时相机流**核对交接物品；`vision_capture` 保存交接照片。不要直接把 `vision_capture` 返回的本机 `file_path` 填给 OCR/VOP 的 `recognize_by_photo`：感知服务与 Agent Core 所在容器未必共享文件系统，该动作的 `image_path` 在感知服务端必须可读。先在各卡片确认 `start`/`info` 状态、输入为 Bumi 相机、结果时间晚于本次物品摆放时间。OCR 输出包含 `text`、`items`、`timestamp`；VOP 输出包含 `objects` 与 `timestamp`。无新结果时先排查连线和模型状态，不把旧画面用于交接。相关动作与字段见[平台 OCR 源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/ocr.py)、[VOP 源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/vop.py)。

先获得被录入人的同意，再在 `face_recognition` 卡片以单人清晰照片执行 `register_by_photo`，填写真实姓名并核对返回 `ok=true`、`person_id`。注册是单独的管理员操作，借出 Skill 不自动注册人员。识别前确认卡片已加载、接收 Bumi 相机画面；在卡片上手动执行 `recognize_by_stream`，应得到 `ok=true` 和 `faces`。只有一张 `known=true`、`quality=ok`、姓名非空的人脸，才可作为借用人候选，仍需管理员确认。

当前平台的持续人脸流在识别陌生人时可能保留未命名身份与到访记录；只在现场人员知情的测试场景启用，并在测试结束后停止该卡片。若不希望产生这类记录，不要启动持续人脸流。`recognize_by_stream` 本身是只读查询。[平台人脸卡片说明](https://github.com/4paradigm/phanthymotus/blob/main/perception/README.md)

## 安装与启用

将整个目录复制到 Bumi 主机，在主机上运行：

```bash
python3 scripts/install_local_skill.py
```

脚本默认操作 `/opt/phanthy-motus/data/data.db` 的 `config.skills` 行。它先在数据库同目录生成 `skills-row-backup-bumi-item-handover-*.json`，再按 `slug` 安装或更新，并重新读取核对。数据库路径不同时使用 `--db /实际路径/data.db`。安装过程不会调用相机或改变机器人状态。

刷新平台 Skill 列表，先停用旧版本（如已激活），再激活 `bumi-item-handover`。确认执行器能调用画布绑定的 `ocr`、`vop` 和 `vision_capture`；`active=true` 只说明配置项已启用，不证明当前 Agent 已加载新指令。

## 现场话术

借出：

> 请激活 bumi-item-handover。现在借出笔记本，资产编号 LT-023，配件是电源适配器和电脑包，预计 2026 年 10 月 12 日 18:00 北京时间归还。借用人已同意人脸识别，请先识别镜头前的借用人；我会把设备标签和配件摆到镜头前，请用 OCR 读标签、用 VOP 辅助识别物品类别，再引导我核对并拍照。我会确认识别结果和实物交付。

归还：

> 现在归还 LT-023。原借出记录是我提供的交接摘要，其中配件为电源适配器和电脑包。我会展示标签、主设备和配件；请用 OCR/VOP 辅助核对，再引导我逐项确认、拍照，并等待我确认已经接收。

每一步完成后再给下一条消息。拍照后管理员须打开原图，确认标签、主设备和配件都清晰；如有遮挡，明确要求重拍。示例日期只作演示，实际归还时间由管理员提供。

## 验收清单

| 场景 | 预期结果 |
| --- | --- |
| 正常借出、归还 | 照片有实际路径，管理员确认后才报告交接或核对相符 |
| 单人已注册 | 返回姓名和 person_id，管理员确认后才填入借用人 |
| 多人、陌生人、低质量或无画面 | 不擅自选择借用人；可调整站位重试或由管理员提供姓名 |
| 人脸结果与管理员核对不符 | 标注识别结果不符，不把错误候选写成已识别借用人 |
| OCR 读出完整标签 | 逐字复述供管理员对照，管理员确认后才写入资产编号 |
| OCR 看不清、读错或读到邻近标签 | 标注未确认或冲突，请管理员调整画面并核对实物；不猜编号 |
| VOP 检出支持的类别 | 记录类别和置信度，管理员仍需确认主设备及资产编号 |
| VOP 不支持该类别或未检出 | 明确说明检测局限，不把未检出当作物品不存在 |
| 同型号错物或 OCR/VOP 与管理员所报冲突 | 按实际标签由管理员复核，未解决前不报告核对相符 |
| 少还配件、错物或外观差异 | 逐项列出差异，不报告正常归还 |
| 标签不清或照片模糊 | 不推断物品身份或画面合格；管理员要求后再拍 |
| 没有原借出记录 | 可以留现场照片，但不宣称与借出时相符 |
| 相机未就绪或拍照失败 | 不报告照片已保存，保留工具错误信息 |
| 拍照后交接中止 | 标注未完成交接；实物已交付则单独报告实际状态 |
| 重复安装 | 同一 `slug` 仅一项，其他 Skill 原样保留；无变化时不再生成备份 |

本地验证安装逻辑：

```bash
python3 -m unittest discover -s tests -v
```

自动测试仅验证安装和配置保留；借还话术、相机回执、原图质量与现场交接需要在 Bumi 上人工验收。
