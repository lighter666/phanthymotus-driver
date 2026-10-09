# Bumi 办公物品借还自助核验

Bumi 主持借还流程：识别人脸并比对借还人自报信息，用 OCR 读取资产标签、VOP 核对受支持的物品类别，引导逐项展示配件，再用 `vision_capture` 保存现场照片。借还人无需等待管理员；识别结果不一致时，Bumi 复核一次并询问其是否确认差异、仍请求继续。确认答复会记入摘要，**不会消除识别冲突**。

这是现场核验与留证 Skill，不是正式借还台账。它不能跨会话查历史、自动解码二维码、判断设备功能、证明保管方已实际接收物品，或仅凭同型号外观确认资产编号。借出基线若由借还人提供，摘要会标明来源；归还应提供原借出摘要或记录，否则不能报告“与借出时相符”。

## 前置条件与画布连接

- Bumi 画布已提供 `camera`、`vision_capture`，感知服务已提供 `face_recognition`、`ocr`、`vop`。`vision_capture.start` 返回 `state=ready`，`capture_photo` 成功时返回 `ok=true`、非空 `file_path` 和 `captured_at`。
- 预先征得员工同意并录入人脸库，录入时使用 `register_by_photo` 和真实姓名；借还 Skill 只执行只读的 `recognize_by_stream`，不自动注册。未经录入、未命名或质量差的人脸不能作为已识别人员。
- 停止智能控制后，将 Bumi `camera` 图像输出分别连到 `face_recognition`、`ocr`、`vop`，把三个结果输出分别连到 `decision_core`；`decision_core` 底部执行器端口连到这三个感知卡片和 `vision_capture`。保留 `remote_message → decision_core` 作为文字输入。`vision_capture` 使用 Bumi 驱动内部相机，无需从感知卡片接入图像。
- 在 `vop` 卡片执行 `list_recognizable_objects`，确认目标类别在固定词表中。没有目标类别时只能依赖标签和借还人陈述，不能说 VOP 已识别该物品。[VOP 源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/vop.py)
- 在卡片检查 OCR/VOP 正接收 Bumi 相机的新画面。OCR 结果包含 `text`、`items`、`timestamp`；VOP 结果包含 `objects`、`timestamp`。不要把 `vision_capture` 返回的本机路径直接交给 OCR/VOP 的 `recognize_by_photo`；感知服务与 Agent Core 可能不共享文件系统。[OCR 源码](https://github.com/4paradigm/phanthymotus/blob/main/perception/plugins/ocr.py)

平台持续人脸流可能为陌生人保留未命名身份及到访记录，启用前应让现场人员知情；结束测试后停止不再需要的卡片。`recognize_by_stream` 查询本身不注册人员。[人脸卡片说明](https://github.com/4paradigm/phanthymotus/blob/main/perception/README.md)

## 安装与启用

将整个目录复制到 Bumi 主机，在目录内运行：

```bash
python3 scripts/install_local_skill.py
```

脚本默认更新 `/opt/phanthy-motus/data/data.db` 中的 `config.skills`；数据库路径不同时传 `--db /实际路径/data.db`。它先备份原 `skills` 配置，再按 `slug` 更新并重新读取验证，不更改其他 Skill。刷新 Skill 列表，停用旧版本并激活 `bumi-item-handover`。确认画布绑定的所有卡片能被执行器调用；配置中的 `active=true` 不代表当前 Agent 已重新加载指令。

如果 Bumi 仍要求“请管理员确认”，先在 **Bumi 主机上的这份最新目录**运行只读检查：

```bash
python3 scripts/install_local_skill.py --check
```

期望看到 `版本=2.0.1`、`与本目录 SKILL.md 一致：是`、`包含旧版管理员提问：否`、`其他激活的管理员版借还 Skill：无`。检查失败时，重新运行上面的安装命令，再刷新 Skill 列表、重新激活，并在**新对话**中测试；旧对话历史可能继续带入过去的管理员话术。只把本目录的 `SKILL.md` 安装到 Bumi，不要使用旧版副本。若检查通过而新对话仍要求管理员，再核对是否有画布提示词或其他 Skill 注入了旧流程。GitHub 分支更新本身不会自动更新 Bumi 数据库。

## 自助使用示例

借出时，借还人可以说：

> 我要借出笔记本，自报姓名张三，资产编号 LT-023，配件是电源适配器和电脑包，预计 2026 年 10 月 12 日 18:00 北京时间归还。我同意人脸识别，会按提示展示标签和配件。请核对并拍照。

归还时，借还人应给出原记录：

> 我要归还 LT-023，自报姓名张三。原借出摘要记录笔记本和电源适配器、电脑包，摘要来源是上次 Bumi 对话。我同意人脸识别，请引导我展示物品并核对。

若 Bumi 报告“人脸识别为李四，但自报张三”或“标签 LT-032，与所报 LT-023 不同”，借还人需要明确说明是否确认这个差异并继续。即使答“确认”，结果仍为“存在差异”；可继续留证，但不会变成正常匹配。照片保存后，借还人可在 Bumi 主机打开原图检查。默认照片目录为 `/opt/phanthy-motus/data/vision_capture/photos/`，以卡片实际返回路径为准。

## 验收清单

| 场景 | 预期结果 |
| --- | --- |
| 人脸姓名、标签编号与类别一致 | 列出逐项证据，只表述“与提供的基线一致” |
| 无人脸、多张人脸或质量差 | 调整后重试一次；仍失败则标为人员未通过视觉核验 |
| 人脸与自报姓名不符 | 向借还人确认差异；确认继续也保留人员冲突 |
| OCR 编号与所报编号不同 | 复核一次，保留差异；不能按 VOP 类别一致就放行成“相符” |
| 标签不清、错读邻近标签 | 不猜编号，标明未识别或未关联 |
| VOP 不支持目标类别或未检出 | 标明类别未验证，不把未检出当成物品不存在 |
| 配件未入画或无法识别 | 与视觉检出项分开，记录借还人自述，不称 Bumi 已核对齐全 |
| 归还没有原借出记录 | 可拍照记录，但不得报告与借出时相符 |
| 照片模糊或保存失败 | 不宣称原图已核实；无成功回执时写照片未取得 |
| 借还人拒绝确认差异或中止 | 停止正常核验，摘要反映已发生的事实 |
| 重复安装 | 同一 `slug` 仅一项，其他 Skill 保留；配置不变时不再备份 |

本地安装逻辑测试：

```bash
python3 -m unittest discover -s tests -v
```

自动测试不代替 Bumi 实机的相机、模型、照片与现场流程验收。
