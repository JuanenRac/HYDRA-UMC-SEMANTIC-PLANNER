<!-- =============================================================================
HYDRA-UMC-SEMANTIC-PLANNER - Rule-based mission planner and semantic error recovery
Copyright (C) JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-SEMANTIC-PLANNER banner" width="100%">
</p>

# 🧭 HYDRA-UMC-SEMANTIC-PLANNER

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | 🇨🇳 <b>简体中文</b> | <a href="README_jpn.md">🇯🇵 日本語</a> | <a href="README_por.md">🇵🇹 Português</a></p>

### 🧠 基于规则的任务规划与逻辑恢复系统（LLM 计划中）

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Tests-308%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.1.9-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-0F6CBD.svg" alt="Maturity">
</p>

---

**诚实核查——今天真正能跑起来的部分：** 封闭的原语词汇表（`primitives.py`）、基于规则的任务分解（`decompose.py`）、基于固定 MCU 错误代码表的基于规则的语义错误恢复（`recovery.py`）、拒绝把畸形计划放行而不是直接通过的前置条件校验器（`validation.py`），以及在同一套逻辑之上暴露出来的、基于标准库 `http.server` 的简单 JSON/HTTP 接口（`api.py`：`POST /decompose`、`POST /recover`、`GET /stats`）都是真实且经过测试的（59 个测试，`pytest`），其中包括一个模糊测试：用固定随机种子对数百个随机/无效目标运行 `decompose_goal()`，并断言它永远不会崩溃或返回畸形计划。目前还不真实的部分：这段代码里完全没有任何本地 LLM——`decompose.py` 是针对一个小而固定的目标词汇表（装配/取放/检查）的正则/模板匹配，不是语言理解，而且从未针对真实的 Hailo-10 模块运行过（本环境没有这种模块）。下面的"Agentic Workflow"和"Hailo-10 Optimized"两条特性在同一份 README 中被明确标注为 `(planned)`——它们描述的是 `decompose_goal()` 当前基于规则的内核未来可能被替换成的样子，不是今天已经存在的东西。已交付的具体内容见 `CHANGELOG.md`，尚未完成的部分见下面的路线图。

**规则式规划器的已知限制：** 被否定或取消的目标（"不要……"、"绝不……"）、匹配多个模板的目标、没有对象的目标，或超过 512 个字符的目标都不会产生计划。对象取自动词之后的词，而不是句子的最后一个词。分解结果是提案而不是命令：`POST /decompose` 返回 `executable: false`，并附带指纹、估算成本和易读的说明；`POST /release`（或 `release_for_execution()`）会根据计划重新计算成本和说明，并核对批准的指纹，之后才允许执行。批准目前尚未签名：它只写明了人员，并不是凭证。`FailureContext.attempt` 使 `TIMEOUT` 和 `GRIP_LOST_SEAL` 的恢复在自动尝试 1 次和 3 次后升级给操作员处理。

---

> **安全与安防现状:**本生态系统不是经认证的安全系统。目前尚无硬件 E-STOP 通路,没有由固件强制执行的限位或联锁,也没有经过验证的运动指令;固件映像使用 CRC-32 和 Ed25519 签名校验,发布构建会拒绝已公开的开发密钥(中继之后的工具头和扩展板仍运行 URTC 的引导程序,它们使用共享密钥的 HMAC-SHA256 而不是签名);TLS 与双向 TLS 均为可选项,默认关闭;自制电路板尚未组装或测试。在依赖此处任何说法来保障人身安全之前,请先阅读[安全基线](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md)和[威胁模型](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md)。

---

## 📋 速览

| | |
|---|---|
| 版本 | `0.1.9` |
| 成熟度 | 可用 |
| 测试 | 308 (`python -m pytest -q tests`) |
| 技术栈 | Python / local LLM (Llama-3 class) |
| 目标 | HYDRA-UMC 工作单元的 Raspberry Pi CM5 |
| 真实硬件 | 不适用：这里的内容不在硬件上运行 |

**跳转：** [概述](#-概述) · [架构](#-架构) · [安全与防护](#-安全与防护) · [配置](#-配置) · [快速开始](#-快速开始) · [测试](#-测试) · [仓库结构](#-仓库结构) · [相关项目](#-相关项目)

## 🚦 项目状态

每一行是本仓库的一个部分，灯号表示它今天做到了哪一步。内容依据仓库能够展示的证据（测试、构建、运行），而不是计划。

🟢 已完成并验证 · 🟡 可用，有已知限制 · 🟠 部分完成或尚未验证 · 🔴 未完成或不可用

| 领域 | 状态 | 在这里的含义 |
|---|---|---|
| 软件 | 🟡 | 主要用途可用；上面的诚实性检查列出了仍然缺少的内容 |
| 测试 | 🟢 | 308 项自动测试，每次变更都会运行 |
| 真实硬件 | 🟢 | 不适用：这里的内容不在硬件上运行 |
| 接口与协议 | 🟡 | 提供的路由或消息已有文档，并用客户端测试过；尚未被所有客户端使用 |
| 集成 | 🟡 | 在 CM5 测试台上与其他服务一起运行，其消息遵循 SDK 的共享契约 |
| 安全性 | 🟡 | 访问控制、输入限制或签名已实现并在计算机上测试；项目之外无人审查过 |
| 部署 | 🟡 | 作为服务安装在 CM5 测试台上，带有安装脚本和单元；每次更新都会重启 |
| 运维 | 🟡 | 以 Prometheus 文本格式提供 /metrics 和健康摘要；尚未接入监控面板 |
| 更新 | 🟡 | 通过 HYDRA-UMC-UPDATER 更新（签名的发布列车、备份和回滚已在计算机上测试） |
| 规划 | 🟠 | 规划器在模拟场景和脚本化目标上工作；从未为真实机器人规划过 |
| 文档 | 🟢 | 八种语言的 README，每次变更都会与清单核对 |

## 🎯 概述

**HYDRA-UMC-SEMANTIC-PLANNER** 是认知 AI 节点的"逻辑编排器"。它使用本地
LLM（大语言模型）将复杂目标分解为可执行的机器人操作单元。

它处理高层次的模糊性，并提供语义级错误恢复：如果一项任务失败（例如"真空
吸盘失去密封"），规划器会推理失败原因，并决定是增加压力、重试，还是更换
为机械工具。

### 关键特性：
* 🧩 **任务分解（v0）：** 对一个已知的小型目标词汇表进行真实的、基于规则的分解（例如"组装 PCB"），得到顺序的机器人指令。*（已实现为真实的模板规则——尚非 LLM；见下方"构建与发布"）*
* 🛡️ **语义恢复（v0）：** 从结构化的 MCU 错误代码到恢复动作的真实的、基于规则的查找。*（已实现为基于已知代码词汇表的真实显式表格；未知代码始终上报给人类）*
* ✅ **前置条件验证：** 每个分解后的计划在交付之前都会对照每个真实原语真正需要的内容进行检查 —— 失败的计划会被拒绝，而不会被静静地当作可执行状态放行。一个可选的、真实的目标机器人/单元声明能力清单（`validate_plan()`/`POST /decompose` 中的 `capabilities`）还能检测出一个形式上正确、但该机器人从未声明支持的原语步骤。*（已实现）*
* ✅ **沿计划的夹爪状态：** 计划会用一个符号化的夹爪（起始为空）走一遍：夹爪已握着东西时再 GRIP，以及在没有握持物或要释放的不是所握之物时 RELEASE，都是计划在其步骤上的错误，在任何东西移动之前就会发现。计划可以以握着目标结束。步骤的参数是只读且可哈希的（`Params`），因此计划在提出之后无法被修改。*（已实现）*
* 🌐 **JSON/HTTP API(v0.0.8):** `serve` 子命令通过 stdlib 的 `http.server`(`POST /decompose`、`POST /recover`、`GET /stats`)对外暴露与 `decompose`/`recover` 完全相同的逻辑,供非 CLI 调用方使用——默认仅限本地回环,与 `systemd/hydra-umc-semantic-planner.service` 单元一致。完整的真实命令、参数和退出码请见 [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md),完整的公开错误码词汇表请见 [`docs/RECOVERY_CONTRACT.md`](docs/RECOVERY_CONTRACT.md)。
* 🎲 **确定性 + 属性测试：** `decompose_goal()` 已被证明具有确定性（相同目标始终得到相同计划），并针对数百个随机/无效目标进行了 fuzz 测试 —— 从不崩溃，也从不返回格式错误的计划。*（已实现）*
* 🤖 **代理式工作流：** 作为本地代理运行，能够查询系统状态和工具。*（计划中）*
* ⚡ **Hailo-10 优化：** 利用 40 TOPS 算力实现快速的多步推理。*（计划中——需要真实的本地 LLM）*
* 👨‍👩‍👧 **认知 AI 节点子项目：** 作为
  [HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE) 下 4 个同级服务之一运行（与 VLA-Engine、Voice-UI 和 Docs-QA 并列），共享父项目的 HydraOS 镜像和模型权重，而非各自保留独立副本。
* 🩺 **统一的 `GET /health`，默认关闭：** `serve --health-open`（或 `HYDRA_UMC_SEMANTIC_PLANNER_HEALTH_OPEN=1`）使服务以 `{"status": "ok", "service": ..., "version": ...}` 响应 `GET /health`，家族中每个服务的响应体相同；没有该开关时，该路由像不存在的路由一样返回 `404`。非回环地址的调用方必须出示服务的 bearer 令牌，响应体不含路径、配置或密钥。
* 🪪 **HYDRA-UMC-SERVER 的身份（默认关闭）：** `serve --identity-key-file 文件`（或 `HYDRA_UMC_SEMANTIC_PLANNER_IDENTITY_KEY_FILE=文件`）会让服务在自己的令牌之外，也接受服务器在登录时签发的已签名令牌：查看者只能读取而不能更改，没有凭据的请求即使在环回地址上也会被拒绝。不开启该开关时一切照旧。

## 🧩 在 HYDRA-UMC 中的角色

**HYDRA-UMC-SEMANTIC-PLANNER** 把高层目标转换为由封闭的机器人原语词汇组成的计划，并在某一步失败时提出恢复方案。目前它基于规则而不是语言模型；在具名人员批准这份确切的计划之前，计划只是建议。

## 🏛️ 架构

<p align="center">
  <img src="images/architecture.svg" alt="HYDRA-UMC-SEMANTIC-PLANNER architecture" width="100%">
</p>

<details>
<summary>图表的文本版本（Mermaid）</summary>

```mermaid
flowchart TB
    GOAL["High-Level Goal"] --> LLM["Semantic LLM (Hailo-10)"]
    LLM --> SUB["Sub-task Generation"]
    SUB --> EXEC["Execution (Orchestrator)"]
    EXEC -- Failure --> FB["Error Context"]
    FB --> LLM
    LLM --> REC["Recovery Strategy"]
    REC --> EXEC
```

</details>

### 架构与设计决策

本仓库是 Cognitive AI Node 系列的**子项目**——其父项目
[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE) 拥有共享的 HydraOS 镜像和量化模型权重，并将本服务与其另外 3 个同级项目（VLA-Engine、Voice-UI、Docs-QA）一同接入 `docker-compose.yml`：

* **为何本子项目没有自己的硬件/固件/`os/`/`models/`。** 它完全运行在父项目已拥有的 CM5 + Hailo-10 M.2 模块上——将模型权重和 HydraOS 镜像集中保存在一处，可避免整个项目族中出现四份互不一致的、动辄数 GB 的副本。
* **为何采用 `src/` 布局。** 使可安装的包（`hydra_umc_semantic_planner`）与仓库根目录的工具（`bump_version.py`）分离，与生态系统中其他每个 Python 项目所使用的布局保持一致。
* **为何入口点最初只打印身份/版本/角色。** 脚手架（scaffolding）阶段证明了该包在实际目标 Python 版本上能够正确安装、编译并被导入，这发生在添加任何真正的基于 LLM 的规划/恢复逻辑之前，并使那部分后续工作与打包相关的问题相互隔离。此后 `main.py` 已经新增了真实的 `decompose`/`recover`/`serve` 子命令（见下文"构建与发布"）——不带参数的 `run.sh` 仍然只打印身份/版本/角色是刻意为之（一个快速的"包是否正确安装"验证），并不代表 CLI 本身仍然只是个空壳。
* **这如何融入生态系统的其余部分。** 本规划器是认知 AI 节点的决策核心：它消费来自其同级项目 HYDRA-UMC-VOICE-UI 的意图，以及来自其同级项目 HYDRA-UMC-VLA-ENGINE 的动作令牌，并将由此产生的任务决策向下游发送给 HYDRA-UMC-ORCHESTRATOR 进行物理执行。
* **为何 `decompose.py` 是真实的正则规则，而非本地 LLM。** 一个小型真实的目标词汇表（组装/取放/检查）如今已被规则完全且诚实地覆盖——这与兄弟项目 HYDRA-UMC-DOCS-QA 使用真实 TF-IDF 索引而非嵌入模型的理由相同：一个真实的、可测试的内核，未来基于 LLM 的规划器可以在同一个 `decompose_goal()` 契约背后替换它。
* **为何 `recovery.py` 的错误代码与公开恢复契约相匹配。** `INVALID_STATE`/`OUT_OF_RANGE`/`ESTOP_ACTIVE`/`TOOL_INCOMPATIBLE`/`TIMEOUT`/`UNSUPPORTED` 是该适配器设计要返回的真实结构化错误——今天针对这个真实词汇表构建的恢复逻辑，在适配器本身存在之后依然有效，而不必事后再去调和一套并行发明的错误分类。
* **为何 `ESTOP_ACTIVE`/`UNSUPPORTED`/未知代码始终上报给人类。** 与整个生态系统的安全规则一致：IA、UI 和云层永远不能凌驾于物理安全条件之上——本规划器只提出恢复动作，绝不会自行解除 E-STOP，也不会对它无法识别的错误进行猜测。
* **为何 `validation.py` 依然存在，即使 `decompose.py` 的真实模板从未真正产生过无效计划。** 固定的模板可以在构造上保证参数格式良好 —— 未来基于 LLM 的规划器则不能。`validate_plan()` 是那个规划器将必须满足的真实、显式契约，在此处、现在就针对当前唯一存在的规划器进行了验证，以便在更难的东西需要满足它之前，契约本身就已被证明正确。
* **为何 `decompose_goal()` 使用固定的随机种子进行 fuzz 测试，而不是使用 `hypothesis`。** 本项目（与生态系统的其余部分一样）仅依赖标准库 —— 一个对数百个合成目标可重现、带种子的 `random.Random` 循环，在不引入新依赖的情况下，获得了同样的真实属性（从不崩溃，从不返回格式错误的计划）。

**作为 Operation 的计划。** `POST /decompose` 还会返回 `operation`：把提案表示为 SDK 通用的 Operation（`kind` 为 `execute_plan`，`status` 为 `received`，请求中的 `target` 和 `priority`，`params` 中的步骤、目标和指纹；相同的计划对应相同的 `operation_id`）。编排器和作业调度器把它当作任务或作业接收。它不放行任何东西：在 `POST /release` 之前 `executable` 保持 `false`。

## 🔒 安全与防护

批准默认需要签名：`serve` 需要 `plan_approval.key_file` 和 `plan_approval.robot_id`（或 `--approval-key-file 文件 --robot-id ROBOT`），并让 `POST /release` 要求 `robot_id`、`issued_at_ms`、`expires_at_ms`，以及对计划指纹、批准人、机器人和最长一小时的时间窗口计算的 HMAC-SHA256（`plan_approval.algorithm` 设为 `Ed25519` 时为 Ed25519）`signature`；未签名、被篡改、已过期或属于其他机器人的批准不会放行任何内容；`sign-approval` 用于生成这些字段。密钥（至少 16 字节）放在安装目录中的文件里，绝不放进仓库（`plan_approval.require_signed` 设为 `false` 仅用于开发）。批准还须由已登录的人作出：使用 HYDRA-UMC-SERVER 的身份（`--identity-key-file`）时，`POST /release` 需要操作员或管理员的签名令牌，且 `approved_by` 必须是该人；没有密钥时所有放行都会被拒绝并给出原因。`plan_approval.require_identity` 设为 `false` 可放宽（用于没有 SERVER 的台架）。管理员可在运行时修改（`GET`/`POST /settings`，放宽时需确认），STUDIO 会显示该开关。

## ⚙️ 配置

计划模拟（默认关闭）：在配置文件中把 `plan_simulation.enabled` 设为 `true` 后，`POST /plan/simulate` 会根据已声明的约束（工作空间范围、位置目录、可用机器人、单步和整个计划的最长时间、同一时刻只能由一步占用的资源、依赖顺序、每个机器人的夹爪）检查一组步骤，并在模拟时钟上逐步走一遍。它返回的结论会列出每一条被违反的规则及其步骤、数值和限值，并在可推导时给出确定性的修正建议；它从不执行或放行任何东西，无法理解的输入返回 400，绝不会是“通过”。开关关闭时，该路由与以前一样返回 404。参见 `docs/PLAN_SIMULATION.md`。

放行前的安全闸门（默认关闭）：把 `safety_gate.enabled` 设为 `true` 后，`POST /release` 还会向 HYDRA-UMC-SAFETY-ZONES 请求其最近一次结论（`GET /state`），只有该结论是 READY、足够新（`max_age_ms`）且默认已签名（`require_signature`、`algorithm`、`key_file`）时才会放行。它失败即关闭：安全服务无响应、响应不是结论、结论过旧、未签名、被伪造或被重放，以及任何非 READY 的状态，都会带着原因阻止计划放行；仍然需要人的批准。语音意图（默认关闭）：把 `voice_intents.enabled` 设为 `true` 后，`POST /voice/intent` 接收 HYDRA-UMC-VOICE-UI 已解析的意图，对 `start_mission` 在 `voice_intents.mission_goals` 中查找任务；目标随后走 `POST /decompose` 的路径，返回的是仍需 `POST /release` 的提案。`stop` 和 `status` 永远不会变成计划。开关关闭时两者与以前一样。所有数值都在 `configs/semantic-planner.json` 中。

符号规划（默认关闭）：将 `symbolic_planner.enabled` 设为 `true` 后，规则所理解的目标会变成一个小型 PDDL-lite 问题（前置条件、否定的前置条件、添加与删除效果），`decompose_goal()` 的步骤来自由 `max_nodes` 和 `max_plan_length` 限定的确定性广度优先搜索；计划会从初始状态重放，任何前置条件被破坏就丢弃。它只提出建议：`POST /release` 的校验、指纹和人员批准都不变，找不到结果时答复是未匹配，绝不会退回模板。恢复记忆（默认关闭）：将 `failure_memory.enabled` 设为 `true` 后，`POST /recover/outcome` 会记录所建议的恢复如何结束（组件、错误码、动作、SUCCESS 或 FAILURE，仅此而已，绝不保存故障的自由文本），存入由 `max_entries` 和 `ttl_s` 限定的记忆；失败 `min_failures` 次且从未成功的动作会变为 `ESCALATE_TO_OPERATOR`。记忆只能让恢复更加谨慎。所有数值都在 `configs/semantic-planner.json` 中。

部署配置与开发（安全闸门）：通用文件 `configs/semantic-planner.json` 将 `safety_gate.enabled` 保持为 `false`，因此为开发而手动启动的规划器行为一如既往。systemd 单元通过 `HYDRA_UMC_SEMANTIC_PLANNER_CONFIG` 选用的配置 `configs/deploy-cm5.json` 会开启闸门：只有当 HYDRA-UMC-SAFETY-ZONES 返回新鲜、READY 且签名有效的裁决时才放行计划，验证密钥从仓库之外的文件读取（`/etc/hydra-umc/safety-state.key`，绝不打印）。将 `safety_gate.start_without_key` 设为 `true`（该配置如此设置）时，密钥文件缺失或无法使用不会阻止规划器启动：`/decompose` 和各项建议照常工作，`POST /release` 则带着原因拒绝。记忆导出（默认关闭）：将 `failure_memory.export.enabled` 设为 `true` 后，每条记录的结果由独立线程通过有界队列和有界重试发送到本机的 HYDRA-UMC-DATALAKE（`POST /ingest/batch`，类型 `recovery_outcome`，字段 `组件/错误码/动作`，值为 1 或 0；除此之外没有任何内容离开本机）；启动时，记忆会读回数据湖仍保存的失败记录（`load_on_start`），校验每条记录并忽略损坏的，因此重新载入只会让恢复更加谨慎。不在本机的数据湖需要 `token_file` 和 https，或有意设置的 `allow_plaintext`。

## 🚀 快速开始

需要 Python 3.10 或更高版本。

```bash
./build.sh  # Linux, macOS (build.bat on Windows)
./run.sh decompose "assemble the pcb"
./run.sh recover --component gripper --error-code TIMEOUT
./run.sh serve --port 8110
```

## 🧪 测试

运行 `python -m pytest -q tests` 会执行 308 个自动测试。 不需要硬件，也不需要这台机器以外的任何东西。

CI 运行 `HYDRA_UMC_CI=1 python tools/ci_validate.py`，检查清单、文档、八个 README 和图片。

## 🏗️ 构建与发布

需要 Python >= 3.10。

```bash
# Linux / macOS / Git Bash
./build.sh   # 创建 .venv，安装该包（可编辑模式），验证导入
./run.sh     # 运行入口点

# Windows (cmd)
build.bat
run.bat
```

`build.sh`/`build.bat` 不会更改版本号（只有 `python tools/hydra_project_tool.py bump` 才会提升），并运行真实的测试套件（`pytest tests/`）。不带参数的
`run.sh` 的预期输出：

```text
HYDRA-UMC-SEMANTIC-PLANNER v0.1.9
Semantic Planner (Hailo-10) - decomposes high-level goals into robotic primitives and recovers from execution failures.
```

真实的子命令会分解一个目标，或提出一个恢复方案：

```bash
./run.sh decompose "assemble the pcb"
./run.sh recover --component gripper --error-code GRIP_LOST_SEAL --detail "vacuum gripper lost seal"

# Windows
run.bat decompose "assemble the pcb"
run.bat recover --component gripper --error-code GRIP_LOST_SEAL --detail "vacuum gripper lost seal"
```

每个真实的分解后计划在打印之前都会对照 `validation.py` 的真实前置条件进行检查。`decompose.py` 自身的模板总是能通过验证；而一个失败的计划则会被拒绝：

```text
Plan for: "broken" FAILED precondition validation:
  step 1 (GRIP): missing required param 'target'
```

同样的 `decompose`/`recover` 逻辑也可以通过 HTTP 访问,供非 CLI 调用方使用:

```bash
./run.sh serve --addr 127.0.0.1 --port 8109
# 在另一个终端:
curl -s -X POST http://127.0.0.1:8109/decompose -d '{"goal": "assemble the pcb"}'
```

完整的命令、参数和退出码参考请见 [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md),完整的公开恢复错误码词汇表请见 [`docs/RECOVERY_CONTRACT.md`](docs/RECOVERY_CONTRACT.md)。

### 🩺 故障排查

* **`python: command not found` / 构建在第 1 步失败。** 需要 `PATH` 中存在 Python >= 3.10。在 Windows 上，从 [python.org](https://python.org) 安装，并确保安装过程中勾选了"Add to PATH"；`python3` 是 Linux/macOS 上的常见命令名。
* **`build.sh` 无法激活 venv。** `python3 -m venv .venv` 在不同平台上生成的激活脚本路径不同：Linux/macOS 上是 `.venv/bin/activate`，Windows（从 Git Bash 使用的 Windows Python venv 也是如此）上是 `.venv/Scripts/activate`。`build.sh` 已经检查了这两个路径——如果仍然失败，删除 `.venv/` 并重新运行 `./build.sh` 从头重建。
* **`pip install -e .` 失败。** 通常是 `.venv/` 已过期。删除 `.venv/` 文件夹并重新运行 `./build.sh`/`build.bat` 重新创建它。
* **`import OK` 从未打印。** 意味着 `python -c "import hydra_umc_semantic_planner"` 本身失败了——在激活 venv 的情况下重新运行以查看真实的回溯信息。

## 📂 仓库结构

<p align="center">
  <img src="images/repository-structure.svg" alt="Repository structure of HYDRA-UMC-SEMANTIC-PLANNER" width="100%">
</p>

<details>
<summary>目录树的文本版本</summary>

```text
HYDRA-UMC-SEMANTIC-PLANNER/
├── src/hydra_umc_semantic_planner/   源代码
│   ├── __init__.py                   包说明与版本
│   ├── primitives.py                 真实的、封闭的机器人命令原语词汇表
│   ├── decompose.py                  真实的、基于规则的任务分解
│   ├── recovery.py                   真实的、基于规则的语义错误恢复
│   ├── validation.py                 对已分解 Plan 的真实前置条件验证
│   ├── api.py                        简洁的 JSON/HTTP 接口(基于 stdlib http.server),桥接 decompose/recover
│   ├── main.py                       入口点 + 真实的 `decompose`/`recover` 子命令
│   └── approval.py                   计划到达执行层之前必须满足的条件
├── tests/                            真实测试：分解、恢复、验证、api、属性测试、端到端 CLI
├── docs/                             文档与知识库
├── images/                           媒体与图表
├── configs/                          恢复策略配置
├── systemd/                          服务单元
├── tools/                            项目工具和 CI 检查
├── .github/                          CI 工作流和 Issue 模板
├── pyproject.toml                    包的元数据
├── bump_version.py                   显式提升版本
├── bump_manifest_version.py          将 hydra-umc.project.json 的版本与原生版本同步(--sync)
├── build.sh / build.bat              创建 venv、安装（含 dev 附加依赖）、运行测试、验证导入
├── run.sh / run.bat                  运行入口点（转发参数，例如 `decompose`）
├── CHANGELOG.md                      每个版本的变更
├── Dockerfile                        容器镜像
├── build-test.sh                     不修改内容的构建检查
├── hydra-umc.project.json            清单：版本、成熟度、系列
└── test.sh                           运行测试
```

</details>

## 🗺️ 路线图与已知限制

**当前已知限制**

* **第一阶段：** 在 Hailo-10 上部署 VLA 引擎并进行多模态输入处理。
* **第二阶段：** 语义规划器与集群行为模型及长期记忆的集成。
* **第三阶段：** 语音 UI 的低延迟本地执行以及工业噪声消除。
* **第四阶段：** 用于共享目标分解的多智能体协调以及语义恢复优化。

## 🌍 语言

本 README 和仓库文档提供八种语言：英语、西班牙语、德语、法语、意大利语、日语、中文和葡萄牙语（葡萄牙）。它们同时编写，并由 CI 检查八个文件拥有相同的章节和相同的链接。 本仓库没有自己的界面或消息目录，因此没有需要翻译的界面文字。

## 🔗 相关项目

本项目是同一作者(JuanenRac / Electro Hobby 3D)打造的 HYDRA-UMC 机器人生态系统的一部分。值得了解,因为某个请求实际上可能是关于这些项目之一,而非本仓库本身。

**父项目**
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — 面向 Hailo-10 认知流水线(LLM/VLA/语音编排)的集成中枢;本仓库是其自身认知流水线中一个具体阶段或消费者所属的父项目。

**兄弟项目** —— HYDRA-UMC-COGNITIVE-NODE 自身 Hailo-10 认知流水线中的其他阶段/消费者
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — 具备受限、需确认的 Watch 中继的真实语音前端(VAD + 意图解析)。
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — 面向 Vision-Language-Action 模型的真实动作 token 编解码与轨迹生成。
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — 面向本生态系统自身 Markdown 文档的真实纯标准库 TF-IDF 文档检索。
- **[HYDRA-UMC-LOCAL-TECHNICIAN](https://github.com/JuanenRac/HYDRA-UMC-LOCAL-TECHNICIAN)** — 面向生态系统自身的本地、按策略门控的 AI 维护技师——观察、诊断并提出修复建议;两个最高风险等级目前特意尚未实现。

**直接相关**
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — 具备真实 gRPC/Protobuf 健康报告契约与任务状态机的集成中枢;接收本规划器自身的任务决策。

**生态系统中的其他项目**

*核心硬件与平台*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — 机器人手臂主板设计——CM5 主机 + 双核 STM32H745,目标是通过 CAN-OTA/SPI-OTA 协调最多 8 条工具臂(固件处于早期阶段,尚无已组装的电路板)。
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — 面向 CM5 的可复现 Raspberry Pi OS 产品层——只读代理、经过验证的配置/配置文件、WiFi 首次配网。
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — 每个桥接都据此校验自身指令的共享 JSON-Schema 契约与软件作业门限边界(并非经认证的安全功能)。
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — 面向外部机器连接器的声明式适配器清单注册与校验工具；把 SDK 自身的契约理念扩展到外部机器，而不取代工业网关类项目。

*核心后端与客户端*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — 每个控制客户端真正通信的真实无头后端(REST/WebSocket)。
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — 具有实时多机器人 3D 可视化的网页控制面板。
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — 面向多台服务器的桌面(PySide6)集群指挥中心，打包为独立可执行文件。
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — 具有生物识别登录和配对 Wear OS 伴侣应用的原生 Android 控制应用。
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — 具有实时 WebSocket 同步的 iOS/iPadOS 控制应用(Flutter)。
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — 面向机载 7 英寸 DSI 触摸屏的原生触控界面，直接嵌入 CM5 本体。
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — 将完成的模型推送到 STUDIO 自身目录的桌面版图形化 URDF 创建/编辑工具。
- **[HYDRA-UMC-EDITOR-STL](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-STL)** — 桌面 STL 模型编辑器，在 HYDRA-UMC-EDITOR-URDF 编辑的同一模型目录中变换/替换/移除/添加真实部件。
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — 通过 VDA 5050 MQTT 发布者为 AGV/AMR 车队提供的协调边界(仅针对仿真车队测试)。
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — 具备 GRBL 状态/控制字节访问能力的高层 CNC 单元协调器(仅针对模拟器测试)。
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — 面向足式/人形机器人的协调边界,带有 Boston Dynamics Spot 指令发送器(仅针对模拟器测试)。
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — 读取 3 路钥匙/外壳/联锁 GPIO 信号的激光单元协调器(仅针对模拟芯片测试;无法使激光器上膛或发射)。
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — 面向 OpenPnP 贴片机板级流程的安全高层协调器。
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — 面向 Moonraker/Klipper 3D 打印机的安全协调边界，具备真实的受控作业指令。
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — 带有惰性导入 rclpy ROS 2 传输层的协调器(尚未在 ROS 2 环境中运行)。
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — 面向搭载摄像头的无人机的协调边界,带有 MAVLink 指令发送器(仅针对模拟器测试)。

*URTC 工具平台*
- **[URTC](https://github.com/JuanenRac/URTC)** — 面向实体 Universal Robot Tool Controller 板卡的固件，通过 CAN 总线支持 25 种以上工具配置。
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — 面向 URTC 板卡的桌面图形烧录工具，支持 CAN-OTA 以及全芯片 SWD/JTAG。
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — 面向 URTC 板卡的桌面实时 CAN 总线诊断工具，每种工具配置对应一个面板。
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — 通过 Web Serial API 实现的浏览器版 URTC-TESTER 替代方案，无需本地安装。
- **[URTC-GATEWAY](https://github.com/JuanenRac/URTC-GATEWAY)** — URTC CAN 总线前的网关：允许的标识符列表、速率限制和会话密钥；软件已在计算机上测试，尚未在真实总线上测试。

*视觉 AI 节点(Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — 面向 Hailo-8 视觉流水线的集成中枢，具备逐阶段的真实硬件就绪检测。
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — 具备 Hailo 架构/校验和安全加载验证的真实编译模型注册表。
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — 具备真实 HailoRT 集成边界的真实 GStreamer 流水线 + MediaMTX 配置生成器。
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — 以区域状态为授权条件的 Position-Based Visual Servoing 修正律;尚无摄像头位姿估计。
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — 从文件读取物体位置的 v0 区域入侵、校准新鲜度与 E-STOP 请求逻辑;没有检测器为其供数,也尚未连接任何物理 E-STOP。

*编排与集群*
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — 基于真实 HTTP API 的真实优先级任务队列，支持去重。
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — 具备重试/退避与身份不匹配检测的真实基于 gRPC 的车队健康看门狗。
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — 具备真实障碍物/工作空间碰撞校验的真实基于 RRT 的三维路径规划器。
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — 经过多单元收敛属性测试的真实 CRDT LWW-Element-Map 状态同步。

*数字孪生与仿真*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — 面向数字孪生引擎的集成中枢，具备真实的版本兼容性同步契约。
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — 在仿真与真实硬件之间带有软件碰撞联锁的硬件在环路由器(未在真实硬件上测试)。
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — 面向真实 URDF 子集的真实正向运动学与关节限位校验。
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — 具备 YOLO/COCO 标注导出功能的真实程序化 2D 场景生成器。

*数据与分析*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — 具备真实数据摄入/查询 HTTP API 的真实 sqlite3 时序数据存储。
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — 具备漂移监测能力的真实 FFT + 统计基线异常检测器。
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — 基于 DATALAKE 历史数据的真实 OEE/可用率计算，支持可复现的 CSV 导出。
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — 面向 DATALAKE 的真实 CAN/WebSocket 数据摄入管道，支持序列去重。

*工业网关*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — 中继至工业协议的集成中枢，具备真实的指令白名单/背压控制层。
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — 经真实二进制协议客户端会话验证的真实 OPC-UA 地址空间。
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — 具备可选按客户端认证与主题 ACL 的真实 MQTT 代理。
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — 具备降级模式输出的真实 MTConnect `/probe` 与 `/current` XML 端点。

*辅助工具与生态系统运维*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — 基于 DATALAKE/ANOMALY-DETECTOR 的智能摘要与异常高亮面板，具备诚实的统计回退机制。
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — 具备真实、稳定退出码契约的车队 CLI，是 HYDRA-UMC-SERVER 自身 API 的真实在线客户端。
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — 带有触觉提醒模式与配对手机语音中继的 WearOS 伴侣应用(尚未在实体手表上运行)。
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — 面向板卡安装机架的固件，具备真实的工具 ID 解码与 Smart Idle 预热逻辑。
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — 面向热成像/RGB 检测工具头的固件及真实 Python 视觉伴侣程序。
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — 发现、克隆并更新本生态系统中每个仓库的管理类桌面工具。
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** —— 构建即刻可烧录、预装生态系统最新版本的 CM5 镜像的 Windows/Linux 桌面工具,具备类似 Raspberry Pi Imager 风格的首次启动 Wi-Fi/用户/SSH 配置。
- **[HYDRA-UMC-OPS-AGENT](https://github.com/JuanenRac/HYDRA-UMC-OPS-AGENT)** — 维护事件协调器：一个低权限的边缘角色采集经过脱敏的库存/健康快照，一个控制面角色以只读方式渲染它，并请求某个 AI 提供方给出诊断建议——从不应用补丁，也从不部署任何内容。
- **[HYDRA-UMC-DEV-SERVER](https://github.com/JuanenRac/HYDRA-UMC-DEV-SERVER)** — 可复现的开发主机（Raspberry Pi 5 / CM5），保存整个生态系统的源代码，并在持久队列下运行有界的构建/测试任务；这是专用的开发角色，明确区别于运行中的 CM5。

## 📚 文档

更多阅读：

* [生态系统的安全基线](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md)
* [生态系统的威胁模型](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md)
* [本仓库的更新日志](CHANGELOG.md)
* [本仓库的许可证](LICENSE.md)

## 🤝 参与贡献与社区

* 提交 pull request 之前，请运行 `HYDRA_UMC_CI=1 py -3 tools/ci_validate.py`（或 `HYDRA_UMC_CI=1 python3 tools/ci_validate.py`）：它必须输出 `CI_VALIDATION=PASS`。此检查不要运行 `build.sh` 或 `build.bat`；构建不是检查。
* 八个 README 由 HYDRA-UMC-DOCS 中的同一个源生成；请勿手工编辑。修改源文件，再用 `tools/make_readmes.py` 重新生成。
* 不要在 README 中声称尚未运行过的内容：属实时请写“仅模拟”或“尚未在硬件上试过”。
* 请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)、[行为准则](CODE_OF_CONDUCT.md)、[SECURITY.md](SECURITY.md) 和 [SUPPORT.md](SUPPORT.md)。

## 👤 作者

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 许可证

GPL-3.0-or-later - [LICENSE](LICENSE).
