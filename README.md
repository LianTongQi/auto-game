# TimedLauncher

TimedLauncher 是一个 Windows 10/11 64 位游戏日常任务串行启动器。它本身不重复实现游戏自动化功能，而是帮助用户按顺序调用已经安装并配置好的第三方工具，更轻松地完成多个游戏的日常任务。双击启动后，TimedLauncher 会请求管理员权限，依次启动工具、等待对应游戏或工具退出、执行必要的按键操作，并在全部流程结束后自动退出。

完整 Release 已自带仅供本程序使用的 Python 和全部依赖。用户不需要安装 Python，不需要配置环境变量，也不会使用或修改电脑中已有的 Python 环境。

## 支持的程序与游戏

| 顺序 | 自动化程序 | 对应游戏 | 首次配置时选择的文件 |
| --- | --- | --- | --- |
| 1 | [BetterGI](https://github.com/babalae/better-genshin-impact/releases) | 《原神》（Genshin Impact） | `BetterGI.exe` 和 `YuanShen.exe` |
| 2 | [March7th Assistant](https://github.com/moesnow/March7thAssistant/releases) | 《崩坏：星穹铁道》（Honkai: Star Rail） | `March7th Assistant.exe` 和 `StarRail.exe` |
| 3 | [OK-WW](https://github.com/ok-oldking/ok-wuthering-waves/releases) | 《鸣潮》（Wuthering Waves） | `ok-ww.exe` 和 `Client-Win64-Shipping.exe` |
| 4 | [OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/releases) | 《绝区零》（Zenless Zone Zero） | `OneDragon-Launcher.exe` |
| 5 | [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases) | 《明日方舟》（Arknights） | `MAA.exe` |
| 6 | [MaaEnd](https://github.com/MaaEnd/MaaEnd/releases) | 《明日方舟：终末地》（Arknights: Endfield） | `MaaEnd.exe` |

> [!IMPORTANT]
> 必须按照表中的顺序安装、配置路径和运行这些程序。每个程序使用的启动参数、完成判断、等待时间和后续按键都不相同；不要交换路径、把程序填入错误的行，或随意调整 `config/tasks.json` 中的步骤顺序。

它不会每日调度，也不会常驻后台。

## 项目结构

```text
TimedLauncher/
├─ config/
│  └─ tasks.json                 流程与本机程序路径
├─ logs/                         运行日志（Git 忽略）
├─ runtime/
│  ├─ python/                    Release 自带的私有 Python 与依赖
│  ├─ launcher.lock              运行时锁文件（自动创建）
│  └─ stop.request               安全停止请求（按需创建）
├─ scheduler_launcher.py         主程序
├─ supervision.py                本轮日志、更新交接和任务完成监测
├─ setup_wizard.py               首次运行路径设置向导
├─ error_report.py               异常退出后的常驻错误报告窗口
├─ verify_runtime.py             检查内置运行环境是否完整
├─ verify_public.py              维护者公开发布审计（仅源码仓库）
├─ launcher_environment.bat      定位内置 Python
├─ start_launcher.bat            显示控制台启动
├─ start_launcher_hidden.bat     隐藏控制台启动
├─ configure_launcher.bat        重新配置程序路径
├─ stop_launcher.bat             安全停止当前流程
├─ runtime_manifest.json         Python 来源、版本与校验值
├─ requirements.txt              固定依赖清单
└─ build_release.ps1             维护者生成便携 Release 的脚本
```

根目录批处理会根据自身位置定位项目，因此移动整个 `TimedLauncher` 文件夹后无需修改项目路径。完整 Release 始终直接调用：

```text
TimedLauncher\runtime\python\python.exe
```

启动器不会寻找系统 Python，也不会联网安装依赖。管理员提权前后继续使用同一个内置解释器。若运行环境缺失、版本不符或依赖损坏，启动器会明确停止并提示重新下载完整 Release，不会退回到电脑中的其他 Python。

## 下载与首次使用

GitHub 源码和 Releases 压缩包分别更新。拉取源码不会自动更新已解压到其他目录的启动器；已下载发布包的实际流程以该包内的配置和说明为准。

1. 打开 [TimedLauncher Releases](https://github.com/LianTongQi/auto-game/releases)，下载最新的 `TimedLauncher-v*-win64.zip`。不要下载 GitHub 自动生成的 `Source code` 压缩包，因为源码包不包含 Python 运行环境。
2. 将 ZIP 完整解压到一个普通文件夹。不要只在压缩软件预览窗口中运行，也不要单独复制 `start_launcher.bat`。
3. 双击 `start_launcher.bat`。程序会先验证内置 Python 和依赖，然后打开首次路径配置向导。
4. 在 Windows 管理员权限提示中选择“是”，让后续自动化工具继承管理员权限。

发布包目前固定使用 Python 3.14.7 64 位。Python 文件只保存在 TimedLauncher 文件夹内，不会安装到 Windows，不会加入 `PATH`，删除整个 TimedLauncher 文件夹即可一并移除。

## 使用方法

首次启动会自动打开中文路径向导。请从第一行开始，严格按照 BetterGI、March7th Assistant、OK-WW、OneDragon、MAA、MaaEnd 的顺序配置；每个游戏主程序路径必须紧跟在对应自动化工具之后。旧版本就地升级后，向导会自动再打开一次以补充 MAA 路径，原有路径会保留。

路径可以留空：未填写完整路径的自动化阶段，以及依附于它的等待、按键和关闭动作，会在正式运行时整体跳过，随后直接进入下一个程序。向导只检查已填写的文件，并把原配置备份至 `config/backups`。它只更新路径和启动程序的工作目录，不会更改 `args` 中已有的启动参数。以后需要修改安装位置时，可以双击 `configure_launcher.bat` 重新打开向导。

首次配置窗口为表中的六个自动化工具提供“GitHub 下载”按钮，直接打开对应项目的 Releases 页面。原神、崩坏：星穹铁道和鸣潮游戏本体没有 GitHub 下载按钮，请通过各自官方游戏启动器安装；这里填写游戏主程序路径仅用于判断对应自动化任务是否完成。

常用入口：

- 双击 `start_launcher.bat` 正常启动。
- 双击 `start_launcher_hidden.bat` 隐藏主控制台启动。
- 双击 `stop_launcher.bat` 请求安全停止。
- 双击 `configure_launcher.bat` 重新配置程序路径。
- 在 UAC 提示中选择“是”，确保自动化工具继承管理员权限。

从指定程序开始运行：

```bat
start_launcher.bat --start-at OKWW
start_launcher.bat --start-at March7th
```

`--start-at` 接受 `launch` 步骤的 `save_as` 或 `name`。

## 当前流程

1. 启动 BetterGI，等待 10 秒并发送 `F10`。
2. 等待原神启动和退出，稳定关闭 10 秒后关闭 BetterGI。
3. 启动 March7th Assistant，等待星穹铁道退出 5 秒后向其控制台发送回车。
4. 等待 5 秒，启动 `ok-ww.exe -t 1 -e`。
5. 如果 OK-WW 报告鸣潮更新完成并自动退出，等待鸣潮以新进程稳定重启 5 秒，再按原参数自动重启一次 OK-WW。
6. 等待鸣潮客户端最终退出 10 秒后启动 OneDragon。
7. 使用参数 `-o -c` 启动 OneDragon，退出 10 秒后启动 MAA。
8. MAA 启动后至少等待 1 分钟；若其自行退出则继续，若运行满 30 分钟仍未退出则强制关闭，并记录超时警告。
9. 启动 MaaEnd，等待 10 秒；确认还未开始任务时发送一次 `F10`，随后持续监测本轮提交的任务，全部成功后才结束流程。

每个自动化阶段最多运行 30 分钟，从工具启动前开始计时，包含启动、更新、重启恢复和退出确认；更新不会重置计时。鸣潮客户端的启动检测时间为 10 分钟，其余启动检测时间见 [config/tasks.json](config/tasks.json)。OneDragon 若还在执行耗时任务但已用完预算，也会按上限停止，不会擅自删减其任务配置。

### 游戏和工具更新

- 日志监视器在启动工具前建立，只使用本轮新增内容，兼容日志轮转、清空和新建文件，不拿上次的成功记录当本次结果。
- 更新下载、安装仍计入本阶段的 30 分钟总预算，不会仅因下载超过 5 分钟就中止。检测到更新完成后，最多等待 5 分钟完成重启交接。鸣潮更新时会确认新的游戏进程稳定至少 5 秒；如果 OK-WW 已退出，再按原参数 `-t 1 -e` 恢复。旧实例仍运行时不会重复启动。
- 工具自更新并换成新进程时会接管新实例。需要手动启动的 BetterGI、MaaEnd 会重新寻找已确认身份的窗口；本轮日志已经显示任务开始时不会再按 F10，避免把任务切换为停止。
- 资源更新完成且工具无需退出时，等待 5 秒确认后继续；不会为了就地更新而重复启动工具。
- 工具更新成功但没有自行重新启动时，确认其关闭至少 15 秒后按原参数恢复一次。普通崩溃、仅检查版本或没有更新证据的退出，不会触发反复重跑。
- 需要重启恢复却找不到更新证据、更新交接超时、达到恢复次数上限或耗尽总预算时，不会盲目重启。MaaEnd 在完成前退出会停止并报告；其他阶段保留原规则，但退出不代表日常成功。更新后若工具更改了可执行文件位置或日志格式，需要重新配置路径或更新对应监测规则；不能保证识别所有第三方版本。

## 配置步骤

流程配置位于 [config/tasks.json](config/tasks.json)，支持以下步骤：

- `launch`：启动程序并用 `save_as` 保存进程别名。
- `wait`：等待指定时长。
- `wait_process_exit`：先确认指定完整路径的进程已启动，再等待其退出。
- `wait_completion`：等待 `target` 的本轮任务日志确认完成，目前用于 MaaEnd。
- `key`：激活别名对应的窗口并发送按键。
- `close`：关闭别名对应的程序及其子进程；配置完整路径时，会关闭该路径下仍存活的实例。

`wait_process_exit` 的时间字段：

- `start_timeout`：等待目标启动的最长时间。
- `minimum_wait`：即使目标提前退出，也至少等待到这个时长后再继续。
- `exit_timeout`：带已知 `setup_key` 的自动化阶段使用从工具启动前开始的总预算；自定义未启用监测的步骤仍从目标首次被检测到开始计时。
- `after_exit`：目标持续关闭多久后进入下一步。
- `timeout_is_error`：设为 `false` 时，超时不会中止整个流程，可由紧随其后的 `close` 步骤关闭目标。

OK-WW 的等待步骤保留了 `restart_on_log`，以兼容自定义流程。标准流程通过 `setup_key` 使用 `supervision.py` 的更新监测，在工具启动前建立日志基线。

## 日志与故障状态

运行日志位于 [logs/launcher.log](logs/launcher.log)，达到 5 MB 后自动轮转，最多保留 3 份历史日志。

`runtime/run_status.json` 原子保存本轮状态、当前阶段、准确步骤编号、最后确认成功的阶段和异常清理结果：`SUCCEEDED` 表示有本轮完成证据，`UNVERIFIED_EXIT` 表示程序已退出但缺少整轮成功证据，`TIMED_OUT` 表示预算耗尽。这些状态不能相互替代；含未确认或 MAA 超时的整轮结果为 `COMPLETED_WITH_WARNINGS`，全部路径留空则为 `NO_TASKS`。BetterGI 的退出游戏脚本可能因游戏关闭而取消自身，这种情况不会被误判为全部日常成功。第三方工具没有稳定完成标记时，保留原先退出后继续的顺序，但明确记录结果未确认。

MaaEnd 需要本轮提交的所有任务 ID 均出现 `Tasker.Task.Succeeded` 才确认结束；`Tasker.Task.Failed` 会立即中止，普通识别失败不会被当成任务失败。按键前会重新核对窗口进程身份和焦点，保留鼠标角落紧急停止功能。辅助子进程的增减不会被当成新一轮，也不会导致重复 F10。启动前已在运行的工具会阻止该阶段重复启动，请先自行结束旧实例。工具在任务完成前退出且没有更新证据时，确认 30 秒后停止，不会继续等待游戏半小时。

关闭命令返回后，最多等待 10 秒确认进程真正退出。Windows 上以进程退出信号为准，不把暂时保留的已结束进程记录误判成仍在运行；进程树关闭命令因部分子进程已消失而返回错误时，也进行同样的退出确认，并复核本轮跟踪的子进程。无法查询退出状态或超时仍未退出时，继续报告真实故障，不会跳过检查。

同一时间只允许一个 TimedLauncher 实例运行。运行锁和停止请求位于 `runtime` 目录，正常退出后自动清理。流程失败时程序会：

1. 记录明确的错误原因；
2. 停止后续步骤，先尝试正常关闭本次启动的程序；
3. 清理本轮实际启动的阶段所关联的工具、子进程和游戏新增实例，不涉及尚未运行或本次跳过的阶段；同时只读 MaaEnd 当前实例的启动动作、OneDragon 的 `game_path` 字段以识别终末地和绝区零路径，不修改它们的配置。启动前已存在的独立进程不会被纳入按路径清理。关闭后再检查残留，清理不完整会写入错误状态；
4. 主脚本退出，同时独立打开错误报告窗口，显示任务、错误原因、详细信息和日志位置；窗口不会自动消失，需手动关闭；
5. 将同一份报告保存到 `runtime/last_error_report.txt`，并返回非零退出状态，不再把失败误报为“全部完成”。

## 从源码构建 Release

Git 仓库只保存源代码、固定依赖清单和运行环境校验信息，不直接提交体积较大的 Python 文件。普通用户应下载 Releases 页面中的完整 ZIP，而不是直接下载源码。

维护者发布时须在 `github-version` 分支操作。`verify_public.py` 会检查公开模板顺序和参数、绝对路径、运行数据，以及常见密钥/凭据标记；它只报告文件名和问题类别，不回显疑似凭据。每次推送前运行它检查待推送的全部提交，不能替代人工审查。`main` 是本机专用分支，不设置远程跟踪、不推送。

维护者可以在 Windows PowerShell 中运行：

```powershell
.\build_release.ps1 -Version 1.1.0
```

构建脚本会完成以下工作：

1. 检查 `config/tasks.json` 中不存在本机程序路径；
2. 从 Python 官方地址下载固定的 64 位 Python 归档并校验 SHA-256；
3. 在临时发布目录中安装 `requirements.txt` 的固定依赖；
4. 验证 Python、Tk 图形界面、依赖版本、自动重启逻辑、首次向导映射和三个启动入口；
5. 生成 `dist/TimedLauncher-v*-win64.zip` 和 `dist/SHA256SUMS.txt`。

下载来源和固定校验值记录在 [runtime_manifest.json](runtime_manifest.json)。发布包中的 Python 保留 Python Software Foundation 提供的许可证文件，各依赖的许可证信息随对应的 `*.dist-info` 目录一同打包。

## Git

日志、锁文件、缓存和本地工具目录不会提交。常用命令：

```bat
git status
git add .
git commit -m "描述本次修改"
```
