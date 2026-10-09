# Bumi 办公物品借还自助核验

此 Skill 只保留两条顺序明确的流程。Bumi 每次只提示当前动作，已获得的信息不再重复询问；异常在当前阶段复核一次并记录，不追加一轮通用核验。

| 借出 | 归还 |
| --- | --- |
| OCR 读取资产标签 → 一次确认配件 → 人脸识别并确认姓名 → 拍照 → 摘要 | OCR 读取归还标签 → 人脸识别并确认姓名 → 一次确认配件 → 摘要 |

归还不拍照。没有原借出记录时仍可完成现场记录，但摘要必须写“缺少借出基线，无法判断是否正常归还”。没有 VOP，Bumi 不能自动识别物品类别或无标签配件；配件状态来自借还人的逐项陈述。借还人确认差异不等于差异消失。此 Skill 不查询跨会话台账，也不证明正式登记或保管方实际接收。

## 画布与直接调用

- 保留 Bumi `camera → ocr → decision_core` 和 `camera → face_recognition → decision_core` 的图像与结果连线；`decision_core` 底部执行器端口连到 `ocr`、`face_recognition`、`vision_capture`。保留原有文字/语音输入。`vision_capture` 使用 Bumi 驱动内部相机。
- 借出和归还展示标签后均调用 **`ocr(action="start", input_topic=画布实际连接的相机话题)`**，然后等待本次展示后的新 OCR 流结果 `text/items/timestamp`；`start` 的返回值不是识别出的文字。使用画布绑定实例与实际话题，不猜话题、也不省略它；无话题的 `start` 可能只进入单张图片按需模式。同一交接不重复启动 OCR。[OCR 卡片源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/ocr.py)
- 人脸阶段在借还人同意且面向相机后调用 **`face_recognition(action="recognize_by_stream")`**。它是只读识别；Skill 不调用 `register_*`。人脸库需事先经本人同意录入真实姓名。[人脸卡片说明](https://github.com/4paradigm/phanthymotus/blob/main/perception/README.md)
- **仅借出**在准备好画面后调用 **`vision_capture(action="start")`**；就绪后调用 **`vision_capture(action="capture_photo")`**。只有成功回执含非空 `file_path` 才写“照片已保存”。归还分支不调用此卡片。
- VOP 不参与本 Skill，`requiredTools` 只有 `camera`、`ocr`、`face_recognition`、`vision_capture`。旧画布上的 VOP 连线可移除；若其他流程仍需要它，可保留独立使用。

## 示例对话节奏

借还人说“我要借出”，Bumi 才提示“请把资产标签对准相机”。读到编号后只问“识别到 LT-023，对吗？”；确认后再问一次配件清单；随后提示面向镜头做人脸识别；最后提示摆好物品拍照并输出摘要。借还人说“我要归还”时按表中归还顺序走，到配件回答后直接输出摘要。

已在开场提供的姓名、资产编号、配件或原记录直接使用，不重复追问。物品名称、预计归还时间、外观和实际取走/放回状态未提供时写“待补”；不为补齐它们增加阶段。OCR 读不清、编号不符、识别姓名被否认或配件冲突时，只在当前阶段重试一次；若仍冲突，问借还人是否确认差异并继续，摘要仍标记异常。说“取消”立即停止后续调用。

## 安装与检查

将本目录复制到 Bumi 主机，在目录内运行：

```bash
python3 scripts/install_local_skill.py
python3 scripts/install_local_skill.py --check
```

脚本默认操作 `/opt/phanthy-motus/data/data.db` 的 `config.skills`，会先备份旧配置、按同一 `slug` 更新，并重新读取验证；其他 Skill 保持不变。数据库在别处时使用 `--db /实际路径/data.db`。检查应显示 `版本=2.2.0`、`与本目录 SKILL.md 一致：是`、`包含旧版管理员提问：否`。刷新并重新激活 Skill，在新对话中测试。推送 GitHub 分支不会自动修改 Bumi 数据库。

## 验收

| 场景 | 预期结果 |
| --- | --- |
| 正常借出 | OCR → 配件 → 人脸 → `start`/`capture_photo` → 摘要，照片路径来自成功回执 |
| 正常归还 | OCR → 人脸 → 配件 → 摘要，`vision_capture` 调用次数为零 |
| 已提前提供信息 | 不重复询问，不增加额外外观/归还时间/交接确认阶段 |
| OCR 无新结果或读错标签 | 当前阶段重读一次；仍失败标记编号未核验或冲突 |
| 人脸未知、多人或姓名被否认 | 当前阶段重试一次；仍不明确标记人员未核验或冲突 |
| 少还配件 | 与已有原记录逐项比较，复核后仍缺少则保留差异 |
| 归还无原记录 | 继续生成摘要，但不能称正常归还 |
| 借出拍照失败或取消 | 不报告留证成功；不执行未发生的步骤 |
| 重复安装 | 同一 `slug` 仅一项，其他 Skill 不变；配置不变时不再备份 |

本地安装测试：`python3 -m unittest discover -s tests -v`。自动测试无法代替 Bumi 实机的调用顺序、OCR 结果、人脸结果与照片回执验收。
