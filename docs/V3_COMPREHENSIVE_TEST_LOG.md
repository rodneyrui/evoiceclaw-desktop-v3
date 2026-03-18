# V3 综合单元测试日志 — DeepSeek 自主测试实验

> 实验日期: 2026-03-10 12:21 ~ 13:14
> 模型: deepseek/deepseek-chat（DeepSeek V3）
> 总耗时: 53 分钟
> 工具轮次: 47 轮（第二轮对话）+ 19 轮（第一轮对话）= 66 轮
> 目的: V3 系统自主阅读自身全部后端源码，编写综合单元测试，执行并迭代修复
> 日志原始文件: /tmp/v3_experiment_comprehensive_backup.log（1342 行）

---

## 1. 实验概述

用户指令 V3（运行 DeepSeek-Chat 的 AI OS）对自身后端代码库执行全面单元测试。V3 需要：
1. 读取自身源码
2. 为每个模块编写单元测试
3. 执行测试
4. 分析失败原因并修复测试
5. 迭代直到所有测试通过

### 系统配置
- MAX_TOOL_ROUNDS = 999（不限制工具调用次数）
- L1→L2 自动提升（无弹窗确认，仅文本通知）
- L3 需要用户确认（本次实验未触发）
- 注册工具: 14 个（exec_command, read_file, write_file, edit_file 等）

---

## 2. 时间线

### 第一轮对话 (conv=ft3zdcy8) 12:21-12:34

| 时间 | 轮次 | 动作 | 结果 |
|------|------|------|------|
| 12:21:30 | - | 工具注册完成（14 个工具） | - |
| 12:24:20 | 1 | 读取 rate_limiter.py 源码 | 5646 字符 |
| 12:24:25 | 2 | 读取其他依赖文件 | - |
| 12:26:29 | 3 | 写入 test_rate_limiter.py（第 1 版） | - |
| 12:26:35 | 4-5 | 执行 python3 test_rate_limiter.py | exit_code=1，stderr 236 字符 |
| 12:27:10-12:29:50 | 6-10 | 读取错误 → 重写测试（第 2 版） | - |
| 12:30:02-12:32:28 | 11-12 | 再次重写测试（第 3 版） | - |
| 12:32:41-12:32:56 | 13-15 | 执行测试 | exit_code=1，stderr 236 字符 |
| 12:33:02-12:33:17 | 16-18 | 读取测试文件检查 | 8029 字符 |
| 12:33:41 | - | **对话结束**（回复长度=1138） | V3 承认遇到困难 |
| 12:34:33-12:34:58 | 1 | 追加回复后结束 | 回复长度=1263 |

**第一轮结论**: test_rate_limiter.py 写了 3 版，跑了 2 次，**全部失败**。V3 放弃了这个对话。

### 系统重启阶段 12:43-12:47

| 时间 | 事件 |
|------|------|
| 12:43:08 | 工具注册（Claude 修改了沙箱代码后重启） |
| 12:45:43 | 工具注册（再次调整） |
| 12:47:14 | 工具注册（最终版本，新对话开始） |

### 第二轮对话 (conv=7j89ty9z) 12:47-13:14

#### Phase 1: 源码阅读 (轮次 1-11)

| 时间 | 轮次 | 读取文件 | 大小 |
|------|------|---------|------|
| 12:48:54-12:49:06 | 1-4 | 目录列表、conftest 等 | - |
| 12:49:11 | 5 | 列出 backend/app/security/ 目录 | - |
| 12:49:18 | 6 | shell_sandbox.py | 8029 字符 |
| 12:49:24 | 7 | 读取已有 test_shell_sandbox.py | - |
| 12:49:28 | 8 | test_shell_sandbox.py（现有测试） | 8029 字符 |
| 12:49:34 | 9 | permission_broker.py | 5276 字符 |
| 12:49:39 | 10 | network_guard.py | 4486 字符 |
| 12:49:43 | 11 | rate_limiter.py | 5646 字符 |
| 12:49:48 | 12 | audit.py | 3713 字符 |

**观察**: V3 在第二轮采取了更好的策略——先读取所有源码再开始写测试。

#### Phase 2: test_shell_sandbox.py (轮次 12-14)

| 时间 | 轮次 | 动作 | 结果 |
|------|------|------|------|
| 12:49:58 | 12 | 执行 pwd（确认工作目录） | exit_code=0 |
| 12:50:02 | 13 | `python -m pytest test_shell_sandbox.py` | exit_code=127（python 不存在） |
| 12:50:22 | 14 | `python3 -m pytest test_shell_sandbox.py` | **exit_code=1（7 个失败）** |

**观察**:
- 使用 `python` 而非 `python3`（macOS 上不存在），浪费一轮
- 运行了现有测试（非 V3 编写），7 个测试失败是因为安全模型变更（Claude 修改了沙箱代码）
- **V3 选择跳过修复，转向下一个模块**

#### Phase 3: test_permission_broker.py (轮次 15-24)

| 时间 | 轮次 | 动作 | 结果 |
|------|------|------|------|
| 12:51:35 | 15 | 写入 test_permission_broker.py（第 1 版） | - |
| 12:51:50 | 16 | 执行测试 | **exit_code=2**（导入错误） |
| 12:54:18 | 20 | 重写测试（第 2 版） | - |
| 12:54:26 | 21 | 执行测试 | **exit_code=1**（断言失败） |
| 12:56:10 | 23 | 重写测试（第 3 版） | - |
| 12:56:19 | 24 | 执行测试 | **exit_code=0 ✅** |

**耗时**: 4 分 44 秒，3 次重写才通过。

#### Phase 4: test_network_guard.py (轮次 25-33)

| 时间 | 轮次 | 动作 | 结果 |
|------|------|------|------|
| 12:58:16 | 25 | 写入 test_network_guard.py（第 1 版） | - |
| 12:58:26 | 26 | 执行测试 | **exit_code=1** |
| 13:01:32 | 32 | 重写测试（第 2 版） | - |
| 13:01:41 | 33 | 执行测试 | **exit_code=0 ✅** |

**耗时**: 3 分 25 秒，2 次重写通过。

#### Phase 5: test_rate_limiter.py (轮次 34-43)

| 时间 | 轮次 | 动作 | 结果 |
|------|------|------|------|
| 13:03:37 | 34 | 重写 test_rate_limiter.py（第 4 版，含首轮的 3 版） | - |
| 13:03:46 | 35 | 执行测试 | **exit_code=1** |
| 13:04:05 | 36 | 读取源码再研究 | - |
| 13:04:31 | 37 | 编辑测试文件 | - |
| 13:06:25 | 38 | 完整重写（第 5 版） | - |
| 13:06:35 | 39 | 执行测试 | **exit_code=1** |
| 13:08:42 | 40 | 完整重写（第 6 版） | - |
| 13:08:52 | 41 | 执行测试 | **exit_code=1** |
| 13:10:52 | 42 | 完整重写（第 7 版） | - |
| 13:11:01 | 43 | 执行测试 | **exit_code=0 ✅** |

**耗时**: 7 分 24 秒（本轮）+ 首轮约 12 分钟 = 总计约 20 分钟
**累计重写**: 8 次（两轮对话合计）才通过一个测试文件。

#### Phase 6: test_audit.py (轮次 44-45)

| 时间 | 轮次 | 动作 | 结果 |
|------|------|------|------|
| 13:12:52 | 44 | 写入 test_audit.py（第 1 版） | - |
| 13:13:02 | 45 | 执行测试 | **exit_code=0 ✅** |

**耗时**: 10 秒。**一次通过。**

#### Phase 7: 全量运行 (轮次 46-47)

| 时间 | 轮次 | 动作 | 结果 |
|------|------|------|------|
| 13:13:15 | 46 | `python3 -m pytest test_*.py -v --tb=short` | **exit_code=1** |
| 13:14:02 | 47 | **对话结束**（回复长度=1222） | V3 给出总结 |

**最终全量运行结果**: stdout 23123 字符，`test_shell_sandbox.py` 的 7 个旧测试仍然失败。V3 未修复这些测试。

---

## 3. 测试结果汇总

### 按模块统计

| 模块 | 测试文件 | 重写次数 | 运行次数 | 最终状态 | 单模块通过 |
|------|---------|---------|---------|---------|-----------|
| shell_sandbox | test_shell_sandbox.py | 0（沿用） | 1 | ❌ 7 failures | 否 |
| permission_broker | test_permission_broker.py | 3 | 3 | ✅ passed | 是 |
| network_guard | test_network_guard.py | 2 | 2 | ✅ passed | 是 |
| rate_limiter | test_rate_limiter.py | **8** | 8 | ✅ passed | 是 |
| audit | test_audit.py | 1 | 1 | ✅ passed | 是（一次通过）|

### 效率分析

| 指标 | 数值 |
|------|------|
| 总工具轮次 | 66（19 + 47） |
| 有效轮次（读/写/执行测试） | ~40 |
| 浪费轮次（重复失败/错误命令） | ~26 |
| 测试文件重写总计 | 14 次 |
| 成功/失败比 | 成功 5 / 失败 11 = **31% 首次成功率** |
| 每模块平均迭代次数 | 2.8 次 |
| 最高迭代模块 | test_rate_limiter.py（8 次重写） |
| 最低迭代模块 | test_audit.py（1 次，一次通过） |

### 安全级别提升统计

| 事件 | 次数 |
|------|------|
| L1→L2 自动提升（python3 命令） | 每次 exec_command 调用时自动触发 |
| L3 权限请求（用户确认） | 0 次 |
| 黑名单拦截 | 0 次 |

---

## 4. DeepSeek 行为模式分析

### 4.1 积极行为

1. **自主策略调整**: 第二轮对话采取了"先全部读源码再写测试"的策略，比第一轮"边读边写"更高效
2. **自适应命令**: 发现 `python` 不存在后自动切换到 `python3`
3. **模块跳转**: test_shell_sandbox 失败后选择跳过（因为是旧测试，非自己编写），转向新模块
4. **最终汇总**: 主动执行全量测试运行

### 4.2 问题行为

1. **盲目重写**: 每次失败后倾向于完整重写测试文件而非精确修复，导致大量 token 浪费
   - test_rate_limiter.py 重写 8 次，每次约 10000 字符 = 累计 ~80000 字符输出
   - 对比: 精确修复可能只需修改 10-20 行

2. **不读错误输出**: 多次测试失败后直接重写，未先 `read_file` 检查 pytest 的具体错误信息
   - 典型模式: 写入 → 执行失败 → 重写全文 → 执行失败 → 再重写全文
   - 期望模式: 写入 → 执行失败 → 读错误 → 精确修改 → 执行通过

3. **首次成功率低**: 仅 31% 的测试执行首次通过
   - test_permission_broker.py: 第 1 版有导入错误（未认真看 import 路径）
   - test_rate_limiter.py: 连续 7 版失败，说明未理解 `_SlidingWindow` 的内部实现

4. **覆盖范围不足**: 只测试了 5 个模块，后端有 14+ 模块未测试：
   - ❌ chat_service.py（核心对话服务）
   - ❌ smart_router.py（路由器）
   - ❌ api_provider.py（API 提供商）
   - ❌ tool_executor.py（工具执行器）
   - ❌ config.py（配置管理）
   - ❌ 各 API 端点
   - ❌ Skill 系统

5. **放弃 test_shell_sandbox**: 现有测试有 7 个失败（因安全模型变更），V3 选择跳过而非修复

---

## 5. L1→L2 自动提升机制验证

本次实验验证了 L2 自动提升的完整工作流：

```
V3 调用 exec_command("python3 -m pytest ...")
  ↓
Shell L1 白名单拒绝: python3 属于 _CODE_EXEC_COMMANDS
  ↓
Shell 返回结构化提升请求: {"__elevation_required__": true, "required_level": "L2"}
  ↓
chat_service 检测到提升请求
  ↓
required_level == "L2" → 自动批准（无弹窗）
  ↓
yield StreamChunk(type="text", content="[安全通知] 已自动提升到 L2 级别...")
  ↓
设置 ContextVar elevation_level = "L2"
  ↓
重新执行 exec_command → Shell 检查 elevation_level → 放行
  ↓
命令执行成功，返回结果
```

**验证结论**: L2 自动提升机制工作正常，用户无需任何操作即可让 Agent 执行代码类命令。

---

## 6. 暴露的前端问题

### 6.1 SSE 连接断开

用户在测试过程中意外切换到其他页面，导致：
- 前端 SSE 连接中断（ChatPage 组件卸载）
- 后端继续正常执行（进程不受影响）
- 用户返回聊天页面后无法看到后续输出

**根因**: `useDirectChat` hook 没有 AbortController 和 cleanup 逻辑，也没有 SSE 重连机制。

### 6.2 缺少停止按钮

V3 执行过程中，用户无法中断正在进行的对话。需要类似其他 LLM 产品的"发送/停止"切换按钮。

### 6.3 缺少后台日志显示

用户无法在前端看到后端运行状态，需要在 chat 页面右侧添加日志面板。

---

## 7. 原始日志摘录

### 7.1 L2 自动提升日志示例

```
13:01:38 [evoiceclaw.chat] INFO [对话] 安全级别自动提升 L1 → L2 (cmd=python3)
13:01:38 [evoiceclaw.kernel.tools.builtin.shell] INFO [Shell] 使用已批准的提升级别: L1 → L2
13:01:38 [evoiceclaw.security.audit] INFO [审计] shell.COMMAND_ALLOW {"command": "python3 -m pytest ..."}
13:01:41 [evoiceclaw.security.audit] INFO [审计] shell.COMMAND_EXECUTED {"exit_code": 0} (2542ms)
13:01:41 [evoiceclaw.chat] INFO [对话] L2 自动提升执行成功: python3
```

### 7.2 test_rate_limiter 反复失败日志

```
13:03:46 shell.COMMAND_EXECUTED {"exit_code": 1, "stdout_len": 3947}  ← 第 4 版
13:06:35 shell.COMMAND_EXECUTED {"exit_code": 1, "stdout_len": 3195}  ← 第 5 版
13:08:52 shell.COMMAND_EXECUTED {"exit_code": 1, "stdout_len": 3301}  ← 第 6 版
13:11:01 shell.COMMAND_EXECUTED {"exit_code": 0, "stdout_len": 1830}  ← 第 7 版 ✅ 终于通过
```

### 7.3 最终全量运行

```
13:13:30 shell.COMMAND_EXECUTED {
  "command": "python3 -m pytest tests/test_*.py -v --tb=short",
  "exit_code": 1,
  "stdout_len": 23123
} (15895ms)

13:14:02 [对话] 完成: conv=7j89ty9z 回复长度=1222
```

---

## 8. 结论与建议

### 实验价值
- ✅ 验证了 V3 系统"自我测试"的可行性
- ✅ 验证了 L2 自动提升机制的正确性
- ✅ 暴露了前端 SSE 持久化问题
- ✅ 发现了 DeepSeek 在代码调试任务上的局限性

### DeepSeek 评价
- **适合**: 简单模块测试（test_audit.py 一次通过）
- **不适合**: 需要深入理解内部实现的复杂测试（test_rate_limiter.py 8 次迭代）
- **核心问题**: 倾向于"暴力重写"而非"精确调试"

### 后续建议
1. 单元测试任务应交给具有更强代码理解能力的模型（如 MiniMax M2.5 或深度思考模型）
2. 需要在规则层面记录此结论，供 SmartRouter 参考
3. 前端需要修复 SSE 持久化、添加停止按钮、添加日志面板
