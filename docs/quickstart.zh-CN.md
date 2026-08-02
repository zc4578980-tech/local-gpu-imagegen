# 五分钟快速开始

[English](quickstart.md) | **简体中文**

本路径适用于使用 Python 3.11 或 3.12，且受支持的后端和模型已经在运行的
用户。它不包含后端安装、模型下载和图像生成所需时间。

## 1. 验证已安装的服务器

```shell
uvx local-gpu-imagegen verify
```

检查点：JSON 应报告 `ok: true`、版本 `0.8.1`，并且恰好包含 17 个工具。
如果不符合，请停止并查看[首次运行问题](#首次运行问题)。

## 2. 添加到 Codex 或 Claude Code

只运行与你使用的客户端对应的命令：

```shell
uvx local-gpu-imagegen setup codex --apply
uvx local-gpu-imagegen setup claude-code --apply
```

检查点：setup JSON 应报告 `applied: true`。该命令会委托给客户端官方的 MCP
命令，不会直接编辑客户端配置文件。它会注册已经解析到的 `uvx` 可执行文件和下面这条
固定当前版本的服务器命令，而不是依赖临时 `uvx` 环境中的控制台脚本：

```text
uvx --from local-gpu-imagegen==0.8.1 local-gpu-imagegen serve
```

如果 setup 报告 `client_setup_drift`，说明已有条目使用了不同的启动器。不要直接编辑
客户端配置；请先执行[回滚客户端配置](#回滚客户端配置)中对应客户端的 remove 命令，
再重新执行一次 setup。启动 ComfyUI 不能修复 MCP 启动器故障；只有客户端成功加载
服务器后，才进入后端就绪检查。

## 3. 重启或重新加载客户端

重启或重新加载选定的客户端，然后确认其 MCP 服务器列表中包含
`local-gpu-imagegen`。仅有 setup 成功结果，并不能证明正在运行的客户端已经加载
服务器。

## 4. 检查后端就绪状态

```shell
uvx local-gpu-imagegen doctor
```

检查点：doctor 应报告选定后端可以访问。尚未运行的后端或模型不属于这条五分钟
路径。`ready: false` 可以是后端停止时的有效诊断状态，不表示 MCP 协议失败。

## 5. 运行一个受支持的工作流

对于一个受支持的普通 ComfyUI API 工作流，请启用 Developer mode，使用
`Save (API Format)`，然后向 Codex 提出：

```text
Run this supported ComfyUI API workflow from Codex: <path>.
Use this prompt: <prompt>. Preserve every other workflow setting.
```

首次使用需要做三个首次决策。同一已验证模型上的新工作流需要两个决策；已经信任且
未变化的工作流只需要一个执行决策。MCP 表面始终保持恰好 17 个工具。

### 文件验证决策

Codex 先执行仅 API 发现，调用 `local_gpu_inspect_workflow`，随后针对一个明确的
本地模型路径规划 `local_gpu_discover_models` 的 `exact_file` / `verify` 操作。
在完整读取模型文件之前，它会显示路径、加载器名称、字节大小、完整文件读取成本、
过期时间和精确确认文本。只批准将来对这个确切路径的读取。该批准不会授予信任、注册
工作流、批准路线或提交提示词。

后续进程只会自动重新验证工作流引用的模型。相同 SHA-256 可恢复加密清单，无需再次
确认；路径、文件状态或摘要发生漂移时，必须重新进行文件验证决策。

### 准备决策

在获得当前 API 身份和加密文件系统身份后，Codex 会以不写入状态的方式检查确切组件
绑定。随后它会显示工作流哈希、默认值、端点、组件、请求的覆盖项、限制，以及两条要
保存的确认信息。只有完整提案可见后才能批准。`local_gpu_register_workflow` 会写入
一份不可变副本，私有信任则绑定同一工作流、端点和组件。信任失败时会留下不可执行的
注册记录并停止。

### 执行决策

Codex 调用 `local_gpu_recommend_models`，解析并显示一条精确路线、全部提示词和生成
参数、相对导入默认值发生变化的字段，以及一次成功轮次的预算。只有该路线完整可见后
才能批准。随后 Codex 调用 `local_gpu_start_run`，恢复冻结运行，并且只调用一次
`local_gpu_generate_round`。该运行不进行重试、模型切换、CPU 回退、工作流回退或
下载。

成功的第一轮会返回原始图像和持久运行证据，状态为 `generated / unreviewed`。审查和
最终确定属于可选的后续工作，不会阻止首次结果。

检查是只读的，不会启动 ComfyUI 或提交提示词。注册不会授予公开权限或模型下载权限。

请参阅英文仓库中的 retained Codex onboarding session。它是发现、检查、注册和信任
绑定的真实零 GPU 客户端证据，不是生成图像或图像质量证据。

## 基于 Profile 的运行

你也可以让附带的 Agent Skill 根据视觉需求解析一条内置路线。例如：

> 创建一张完整的灯塔环境插画，不要人物、文字、标志或水印。复用我现有的本地后端
> 和模型，禁用下载和模型切换，最多使用两个成功轮次，并在最终确定前询问我。

生成前，Agent 应展示 `local_gpu_discover_models` 的结果、任何必要的
`local_gpu_set_model_trust` 操作、`local_gpu_recommend_models` 的结果，以及精确
选定的路线。它应在调用 `local_gpu_generate_round` 前等待你的确认，展示每张保留图像
供审查，并等待之后单独给出的、绑定到图像字节的最终确认。

两种路径都要求受支持的后端和模型已经运行。UI 格式转换、自定义节点、img2img、
inpaint、区域/两阶段工作流接入、隐式启动后端和模型安装均不属于本快速开始。

## 回滚客户端配置

只移除为本次选定客户端创建的 MCP 条目：

```shell
codex mcp remove local-gpu-imagegen
claude mcp remove --scope user local-gpu-imagegen
```

重启或重新加载客户端，并确认 `local-gpu-imagegen` 不再出现。此操作不会删除本地模型、
后端文件或保留的运行记录。

## 首次运行问题

安装、传输、后端、信任、路线和恢复故障，请查看英文仓库中的 Troubleshooting。
Codex 与 Claude Code 的详细配置方式和当前具名客户端证据边界，请查看英文仓库中的
Client compatibility。
