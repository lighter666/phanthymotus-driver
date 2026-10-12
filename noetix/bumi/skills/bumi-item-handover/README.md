# Bumi 固定资产借还 Skill 原型

员工向 Bumi 申请借用物品；Bumi 人脸核验后，从安装时导入的 CSV 目录中提出一个**候选资产编号**，生成给资产管理员的飞书待转发消息。该管理员负责核对、交付，也负责现场验收归还。管理员在飞书主动给 Bumi 发归还确认后，Bumi 回复核对摘要。

这是静态目录原型。没有库存事务、主动私聊人类管理员或台账写入工具；候选编号未预留，消息未自动发送，归还摘要也不会改写库存。管理员必须核对实时台账和实物，交付或归还后人工更新台账及 CSV，再重新安装 Skill 刷新目录快照。

## 资产目录

[assets.csv](assets.csv) 初始只有表头，不包含虚构的资产。每件资产一行，UTF-8 CSV：

| 字段 | 用途 |
| --- | --- |
| `asset_id` | 唯一资产编号；按字符串保留字母、前导零和连接符 |
| `asset_name`、`category` | 资产名称、员工借用时匹配的类别 |
| `sn` | 序列号；没有时留空，Skill 显示“未提供” |
| `accessories` | 配件清单；没有配件请明确填“无”，留空表示“未提供” |
| `administrator` | 同一位借出负责人和归还验收管理员的姓名 |
| `administrator_open_id` | 该管理员在本飞书应用中的发送者 ID；留空时无法核验飞书归还确认 |
| `status` | 人工维护的快照状态，只能是“可用”“借出”“停用” |

例如，可在自己的 CSV 中写入 `0007,投影仪,投影仪,SN-001,电源线1根,张三,ou_example,可用`；这只是填写格式示意，不是仓库中的真实资产。相同类别的可用资产按完整编号字符串升序选首项。静态快照不能阻止并发请求得到同一候选编号。

## 借用与归还

**借用：** 员工说出要借的类别或物品 → Bumi 用 `face_recognition(action="recognize_by_stream")` 核验公司员工 → 从目录提出候选编号、SN、配件和管理员 → 播报“未预留，待管理员核对” → 输出给管理员的飞书待转发正文。负责人实际交付后，由人工更新台账和 CSV。没有真实交付及保存回执时，不输出“已借出”。

**归还：** 借用人与同一位管理员现场核对主设备和配件 → 管理员从飞书主动给 Bumi 发含资产编号、原借用记录、差异及接收实物确认的消息 → Bumi 根据本次飞书事件的发送者 ID 和 CSV 中的 `administrator_open_id` 核对身份 → 使用 `channel_reply` 与本次 `source_message_id` 回复核对摘要。缺身份、原记录或配件信息时列出缺项与差异；管理员人工更新台账和 CSV。

现场语音请求不会产生一个可回复的管理员飞书会话。[PhanthyMotus 飞书 Channel 文档](https://github.com/4paradigm/phanthymotus/blob/main/docs/feishu-channel-setup.md)中的 `channel_reply` 用于回复触发的消息或向已配置的对端机器人发起协作，不能在这里假设它可以主动私聊任意人。因此借用时仅生成待转发文本；归还时管理员需先给机器人发消息。飞书 Channel 须已配置并接入 `channel_request → decision_core → channel_reply`。

## 安装与检查

在 Bumi 主机上复制整个目录。先填写真实资产 CSV，再运行：

```bash
python3 scripts/install_local_skill.py --validate-assets
python3 scripts/install_local_skill.py
python3 scripts/install_local_skill.py --check
```

脚本默认操作 `/opt/phanthy-motus/data/data.db` 的 `config.skills`；数据库不同则加 `--db /实际路径/data.db`，CSV 不同则加 `--assets /实际路径/assets.csv`。安装前备份旧配置，按同一 slug 更新并保留其他 Skill；`--check` 对比数据库中的完整指令与当前 Skill **及 CSV 快照**。检查版本应为 `4.0.0`。修改 CSV 后必须重新运行安装并重新激活 Skill，否则 Bumi 仍使用上一次快照。推送 GitHub 不会自动安装到 Bumi。

## 验收

本地运行 `python3 -m unittest discover -s tests -v`。测试覆盖 CSV 格式、重复编号、前导零、候选排序、空目录、重复安装和快照变化。Bumi 可连接后，分别用现场借用和管理员飞书归还消息检查人脸结果、实际事件 ID、`channel_reply` 的原消息绑定以及每一步的状态用语。无实机访问时，本地测试不能证明飞书已送达或资产已交付。
