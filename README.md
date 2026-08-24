# TimedLauncher

TimedLauncher 是一个 Windows 游戏日常任务串行启动器。它本身不重复实现游戏自动化功能，而是帮助用户按顺序调用已经安装并配置好的第三方工具，更轻松地完成多个游戏的日常任务。双击启动后，TimedLauncher 会请求管理员权限，依次启动工具、等待对应游戏或工具退出、执行必要的按键操作，并在全部流程结束后自动退出。

## 支持的程序与游戏

| 顺序 | 自动化程序 | 对应游戏 | 首次配置时选择的文件 |
| --- | --- | --- | --- |
| 1 | [BetterGI](https://github.com/babalae/better-genshin-impact/releases) | 《原神》（Genshin Impact） | `BetterGI.exe` 和 `YuanShen.exe` |
| 2 | [March7th Assistant](https://github.com/moesnow/March7thAssistant/releases) | 《崩坏：星穹铁道》（Honkai: Star Rail） | `March7th Assistant.exe` 和 `StarRail.exe` |
| 3 | [OK-WW](https://github.com/ok-oldking/ok-wuthering-waves/releases) | 《鸣潮》（Wuthering Waves） | `ok-ww.exe` 和 `Client-Win64-Shipping.exe` |
| 4 | [OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/releases) | 《绝区零》（Zenless Zone Zero） | `OneDragon-Launcher.exe` |
| 5 | [MaaEnd](https://github.com/MaaEnd/MaaEnd/releases) | 《明日方舟：终末地》（Arknights: Endfield） | `MaaEnd.exe` |

> [!IMPORTANT]
> 必须按照表中的顺序安装、配置路径和运行这些程序。每个程序使用的启动参数、完成判断、等待时间和后续按键都不相同；不要交换路径、把程序填入错误的行，或随意调整 `config/tasks.json` 中的步骤顺序。

它不会每日调度，也不会常驻后台。

## 项目结构

```text
TimedLauncher/
├─ config/
│  └─ tasks.json                 流程与本机程序路径
├─ logs/                         运行日志（Git 忽略）
├─ runtime/                      锁文件和停止请求（Git 忽略）
├─ scheduler_launcher.py         主程序
├─ setup_wizard.py               首次运行路径设置向导
├─ launcher_environment.bat      统一定位项目内 Python 环境
├─ start_launcher.bat            显示控制台启动
├─ start_launcher_hidden.bat     隐藏控制台启动
├─ configure_launcher.bat        重新配置程序路径
├─ stop_launcher.bat             安全停止当前流程
├─ install_dependencies.bat      安装 Python 依赖
└─ requirements.txt              Python 依赖清单
```

根目录批处理会根据自身位置定位项目，因此移动整个 `TimedLauncher` 文件夹后无需修改项目路径。Python 环境也位于项目内部：

```text
TimedLauncher\.venv\Scripts\python.exe
```

所有入口都通过 `launcher_environment.bat` 计算该路径，不读取系统默认 Python，也不依赖手动激活虚拟环境。管理员提权时主程序继续使用当前的 `sys.executable`，因此提权前后仍是同一个 `.venv`。

## 首次安装 Python（必须）

TimedLauncher 不包含 Python 本体。第一次使用前，电脑必须安装 **64 位 Python 3.11**；已经安装的用户无需重复安装。

1. 打开 [Python 3.11.9 官方发布页](https://www.python.org/downloads/release/python-3119/)，在页面的 Windows 文件中下载 **Windows installer (64-bit)**；也可以使用[官方安装程序直链](https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe)。
2. 运行安装程序，在第一个页面勾选 **Add python.exe to PATH**。
3. 选择 **Install Now** 并等待安装完成。
4. 安装后重新打开命令提示符，执行以下命令：

```bat
py -3.11 --version
```

如果显示 `Python 3.11.x`，说明 Python 已正确安装。项目只使用它创建 `.venv`；后续依赖都会安装在项目内部，不会写入系统 Python 环境。

## 使用方法

完成上面的 Python 安装后，直接双击 `start_launcher.bat`：如果项目内尚无 `.venv`，启动器会自动创建环境、安装并验证依赖，然后继续打开中文路径向导。无需先执行 `conda activate`，也无需手动选择 Python 环境。

`install_dependencies.bat` 仍可单独运行，用于提前准备或修复环境。安装器只在项目自己的 `.venv` 中安装依赖；任何创建、安装或导入验证失败都会返回错误，不会再误报“依赖安装完成”。完成环境准备后，如果尚未完成首次设置，程序会自动打开中文路径向导。请从第一行开始，严格按照 BetterGI、March7th Assistant、OK-WW、OneDragon、MaaEnd 的顺序配置；每个游戏主程序路径必须紧跟在对应自动化工具之后。

依赖清单固定为本项目已验证的版本，避免不同用户在不同日期安装到行为不一致的新版本。如果 `.venv` 缺失或依赖导入失败，正常启动、隐藏启动和重新配置三个入口都会自动调用安装器修复。

路径可以留空：未填写完整路径的自动化阶段，以及依附于它的等待、按键和关闭动作，会在正式运行时整体跳过，随后直接进入下一个程序。向导只检查已填写的文件，并把原配置备份至 `config/backups`。它只更新路径和启动程序的工作目录，不会更改 `args` 中已有的启动参数。以后需要修改安装位置时，可以双击 `configure_launcher.bat` 重新打开向导。

首次配置窗口为表中的五个自动化工具提供“GitHub 下载”按钮，直接打开对应项目的 Releases 页面。原神、崩坏：星穹铁道和鸣潮游戏本体没有 GitHub 下载按钮，请通过各自官方游戏启动器安装；这里填写游戏主程序路径仅用于判断对应自动化任务是否完成。

常用入口：

- 双击 `start_launcher.bat` 正常启动。
- 双击 `start_launcher_hidden.bat` 隐藏主控制台启动。
- 双击 `stop_launcher.bat` 请求安全停止。
- 双击 `configure_launcher.bat` 重新配置程序路径。
- 双击 `install_dependencies.bat` 手动检查并修复项目环境。
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
5. 等待鸣潮客户端退出 10 秒后启动 OneDragon。
6. 使用参数 `-o -c` 启动 OneDragon，退出 10 秒后启动 MaaEnd。
7. 等待 10 秒，向 MaaEnd 发送 `F10`，随后 TimedLauncher 退出。

所有受监测程序的最长运行等待时间为 30 分钟。鸣潮客户端的启动检测时间为 10 分钟，其余启动检测时间见 [config/tasks.json](config/tasks.json)。

## 配置步骤

流程配置位于 [config/tasks.json](config/tasks.json)，支持以下步骤：

- `launch`：启动程序并用 `save_as` 保存进程别名。
- `wait`：等待指定时长。
- `wait_process_exit`：先确认指定完整路径的进程已启动，再等待其退出。
- `key`：激活别名对应的窗口并发送按键。
- `close`：关闭别名对应的程序及其子进程。

`wait_process_exit` 的时间字段：

- `start_timeout`：等待目标启动的最长时间。
- `exit_timeout`：检测到目标后，等待其退出的最长时间。
- `after_exit`：目标持续关闭多久后进入下一步。

## 日志与故障状态

运行日志位于 [logs/launcher.log](logs/launcher.log)，达到 5 MB 后自动轮转，最多保留 3 份历史日志。

同一时间只允许一个 TimedLauncher 实例运行。运行锁和停止请求位于 `runtime` 目录，正常退出后自动清理。流程失败时程序会：

1. 记录明确的错误原因；
2. 尝试关闭本次流程启动的程序；
3. 返回非零退出状态，不再把失败误报为“全部完成”。

## Git

日志、锁文件、缓存和本地工具目录不会提交。常用命令：

```bat
git status
git add .
git commit -m "描述本次修改"
```
