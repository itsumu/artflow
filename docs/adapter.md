# 接入指南（适配包 schema 2）

第一次接入请先阅读更短的[项目接入指南](integration-guide.md)；本文作为完整字段参考。

## 最短接入路径

1. 用 `artflow init 新目录` 创建可运行的 PNG 像素精灵示例；先运行 check，再启动 Web。
2. 改 `executors` 中的工具启动参数与允许命令。
3. 改 `templates` 的输入、输出路径和管线；同类资产只需增加一个 assets 条目。
4. 用 `artflow plan --project ... --asset ... --action ...` 查看解析后的输入与写入目标。
5. 在 Web 确认执行；日志与产物自动出现在对应步骤。

遇到接入问题时先运行 `artflow doctor --project ...`。`check` 会检查外部输入、
执行器、工作目录和 `version_files`；尚未生成的未来输出不会被误报为缺失输入。

普通项目只需要两个 JSON 文件。无需编写 Artflow 插件或学习 Python。
已有工具可以继续输出普通文本，用退出码表示成功；已有 JSON 报告可直接适配。

## 项目文件

`schema_version: 2`、`project_id`、`label`、`pipelines`、`assets`、`executors` 必填。
所有默认相对路径以 project.json 所在目录为基准，不依赖当前工作目录。
`roots` 命名外部根目录；`storage` 指定运行记录位置，默认 `.artflow-state`。

资产可声明 `template` 复用 templates 中的对象；对象字段递归合并，
数组与标量由资产配置整体覆盖。模板属于项目适配包，核心不内置资产类型。

资产字段：
- label、kind：显示名称与分类；kind 是自由文本。
- metadata：任意显示字段，可为数组或对象，不要求画布、脚点等属性。
- artifacts：ID 到产物描述的映射。
- pipeline：管线 ID。
- preview：默认预览入口的产物 ID 数组；不存在的产物自动隐藏。
- data：可选的已有 JSON 合同文件与 JSON Pointer。

产物字段：label、kind、path、可选 root。
kind 推荐 image、audio、video、json、file；未知类型也可下载。
path 可为字符串，也可引用已有合同字段。

## 读取原合同，不复制参数

```json
{
  "data": {
    "file": "{root.project}/contracts.json",
    "pointer": "/assets/{asset_id}"
  },
  "metadata": {
    "画布": {"$ref": "data.canvas"}
  },
  "artifacts": {
    "source": {
      "label": "源文件",
      "kind": "file",
      "root": "project",
      "path": {"$ref": "data.source"}
    }
  }
}
```

`$ref` 保留原值类型；`strip_prefix` 可处理项目 URI 前缀。
字符串模板支持 `{root.NAME}`、`{asset_id}`、`{project_id}`、
`{python}`（当前解释器），以及 `{data.FIELD}`。
命令与管线还可用 `{artifact.ID}` 获取解析后的绝对路径。
JSON Pointer 使用标准 / 分段和 ~0、~1 转义；字段引用使用点分段。
未知字段、根目录或引用会报错，不会静默替换成空字符串。

## 执行器

```json
{
  "argv": ["{python}", "{root.project}/tool.py"],
  "cwd": "{root.project}",
  "allowed_commands": [
    ["build", "{artifact.input}", "{artifact.output}"]
  ],
  "version_files": ["{root.project}/tool.py"],
  "response": {"format": "exit_code"}
}
```

最终执行命令 = argv 前缀 + 步骤 command 参数数组。没有 shell 拼接；
网页不能提交任意命令。白名单在模板解析后进行精确数组比较。

`response.format`：
- exit_code：退出码 0 且声明输出存在才通过。
- json：stdout 必须为 JSON 对象，退出码为 0，success_field（默认 ok）
  必须严格为 true；required 对象可指定协议字段及期望值。

`version_files` 列出影响结果的脚本、依赖锁文件等；其内容变化使旧结果失效。
工具实际版本不自动猜测，应纳入文件或适配器配置；二进制可明确列入。
`inherit_env` 控制继承的环境变量名；默认 PATH、HOME、TMPDIR、LANG、LC_ALL。
`env` 添加确定的环境值。工具秘密不要写入版本控制的适配包。

## 管线与操作

管线文件同样声明 schema_version: 2，包含 pipelines 对象。每条管线有
steps 数组和 actions 对象。

步骤字段：
- 每个输出文件只能有一个生产步骤；多阶段加工请使用不同中间文件路径。
  需要原地修改同一文件的多个命令可封装为一个工具步骤，核心不保存文件历史副本。
- id、label、kind（read 或 command）。
- inputs、outputs：具体产物 ID 数组；内存报告直接记录在步骤记录中。
- depends_on：生产依赖，决定拓扑顺序、路径冲突与失效传播。
- command 步骤还需 executor、command、timeout_seconds、retry_policy、
  writes（显式布尔值）。
- 声明 outputs 的 command 步骤必须设置 writes: true，不能绕过审批边界。
- 写入步骤需 outputs、locks、requires_approval: true、approval_artifacts。
  审批产物必须同时声明为 inputs。
- 可选 description 提供面向操作者的说明。

actions 是用户可执行入口，每个含 label、steps 和可选 description。
核心按 DAG 顺序执行所选步骤，**不会隐式运行入口以外的制作步骤**。
例如“生成候选”“提升正式源”“导出并验证”应是不同入口。

入口以现有输入为检查点，计划会列出并绑定这些文件的哈希；适合接入
已有制作到一半的资产。已知生产步骤被标记过期或失败时，不能直接复用
它的输出，需要先重新执行对应生产步骤。
没有历史记录的已有文件可在当前入口明确审阅后使用，作为导入检查点记录。

若一个步骤需要人工审阅前一步刚生成的图像，两者必须拆成不同 action，
避免在图片尚未生成时预先批准。配置检查会拒绝这样的合并。
已有审阅通过的正式源 → 导出 → 自动验证可以放在同一 action。

`publish_artifacts` 可指定一次操作成功后代表“已验证版本”的文件。
没有该字段的候选制作只记录完成，不冒充发布验证。

## 锁、失败和重试

locks 使用本机共享名字，例如某制作软件的独占通道；可用
`asset:{project_id}:{asset_id}` 表示资产。
核心同时为本次访问的文件路径加锁，同一物理文件跨项目也互斥。
冲突快速失败；页面可查看错误，资源释放后重新打开计划执行。

超时和取消会终止整个受控进程组。由工具自行脱离进程组启动的后台
应用不受此机制控制，适配器应优先使用阻塞批处理入口。
失败会停止后续步骤并保留记录。自动回滚不由核心猜测；制作工具应
使用临时文件后原子替换。retry_policy 是重试语义说明，当前不会自动
重试任何写入；人工重试总是创建新计划、新记录。

声明 outputs 并不是系统写入沙箱。项目工具如需产生缓存、归档或导入
元数据，应在适配说明中列明，并为这些副作用声明对应共享资源锁。
