# 明日方舟助手：只读分析原型 0.1

这是 TimedLauncher 的独立功能原型，尚不是全自动开荒/养成系统。源码位于项目 `features/arknights_assistant`，可以独立部署为 `ArknightsAssistant` 文件夹。它不修改启动器日常配置、不添加调度任务、不请求管理员权限。

## 已实现

- 中文桌面界面与命令行，提供演示、导入、查询、分析和保存报告。
- 导入干员名称数组，或包含 `operators` / `own_opers` / `all_opers` 的 JSON。`all_opers` 仅纳入明确 `own=true` 的干员。没有验证所有 MAA/一图流导出版本；遇到未知格式停止并提示，不猜测。
- 导入库存和用户准备的材料需求清单；计算明确缺口。未识别到的材料数量显示“未知”，不默认为零。
- 检查作业需要的精英阶段、等级、所选技能等级、潜能、模组，以及替换组；防止同一干员重复占据不同位置。
- 匿名只读查询 PRTS Plus 公开作业，一次一页、最多 20 条摘要、最多读取 3 份关卡匹配的完整详情、每次请求 15 秒网络超时。列表响应可能不包含动作，因此不能直接把摘要当成完整作业。只发送关卡编号和分页条件，不上传账号、干员或库存。
- 导入并检查作业的非空 `actions`；关键词搜索命中仍需要精确关卡匹配。暂未验证关卡首通、演习或作业成功率。
- MAA 文件检查和原生 `AsstGetVersion` 探测。不会创建 MaaCore 实例，不连接 ADB，不运行更新器，不启动模拟器或游戏。

## 明确未实现

- 自动扫描当前游戏界面并获取真实账号；当前需要导入数据。
- 自动演习、调整编队、正式作战、助战选择、活动地图导航。
- 自动决定培养对象、计算全部升级/精英化/模组配方，或执行升级、专精、合成。
- 任意视频自动转换作业、自动替换核心干员、无人干预保证通关。

`CANDIDATE` 只表示导入的已知要求匹配，不表示已通关或允许执行。`NEEDS_REVIEW` 表示有未知练度、未支持的要求字段、未声明要求、无编队声明或演示数据。`MISSING_REQUIREMENTS` 表示有缺失/不达标位置。`WRONG_STAGE` 不纳入目标关卡候选。当前仅检查作业结构和阵容要求，尚未完整校验动作协议、最低 MAA 版本或实际通关条件。

## 独立启动

需要 Python 3.10+（桌面版需要 tkinter）。本机部署会显式使用已有 TimedLauncher 私有 Python，不寻找系统环境、不安装新包。

1. 把 `config/config.example.json` 复制成 `config/local.json`。
2. 填写 `python_path`（私有 Python 可执行文件）、`maa_dir`（MAA 文件夹），保留 `analysis_only: true`。
3. 双击 `start_assistant.bat` 打开只读桌面界面。启动即显示带有醒目标记的虚构演示，不自动联网。
4. 双击 `test_demo.bat` 运行演示并保存报告。

材料、干员、作业、需求清单可分别导入；界面中的“检索公开作业”需要填写关卡编号。联网查询失败时不重试，可改用本地作业。

关卡别名从 MAA 的刷图索引和地图总览读取。不同活动可能复用同一编号，例如多期矢量突破的 `VEC-12`；这时会要求填写唯一关卡 ID（本机资源中的第三期为 `act3break_12`），不会把旧活动作业误配到新活动。突袭/普通难度也需要核对，不能仅凭标题判断。

也可通过 `tools/install_feature.ps1` 指定一个尚不存在、末级名称为 `ArknightsAssistant` 的目录，以及准备好的本地配置文件来部署。部署按文件清单复制并逐一校验 SHA256，不覆盖已有目录。

## 数据格式

`examples/inventory.demo.json`、`examples/goals.demo.json` 与 `examples/jobs/` 是虚构测试资料，不可用于游戏。真实导入文件可以参考这些结构，把 `is_demo` 改为 false，并填写经过核实的数据。

技能字段 `skills` 使用所选技能编号（1～3）到等级（1～10）的映射；专精一/二/三对应 8/9/10。`skill_level` 仅用于通用技能等级 1～7，不可代替某个技能的专精。模组字段 `modules` 使用作业协议模组编号到等级的映射；不同数据站模组标识需要显式转换，不可直接猜编号。

未知字段可以省略，这会触发待核验，不会被当成达标。材料以游戏材料 ID 为键。需求清单为已计算好的材料总需求；当前原型不会推导真实养成配方。

## 验证

```text
python -B -m unittest discover -s tests -v
python -B main.py demo
python -B main.py gui --smoke
python -B main.py doctor --probe
python -B main.py analyze --inventory examples/inventory.demo.json --jobs examples/jobs/01-demo.json
python -B main.py search --stage 1-7 --inventory examples/inventory.demo.json
```

报告保存在 `runtime/reports/`，不覆盖旧报告。关闭桌面窗口即退出本功能；无常驻服务。联网后台线程设有超时，不提交游戏任务。

## 隐私与后续集成

`config/local.json`、`data/`、`runtime/` 都必须留在本机，不公开。导入时仅保留必要的干员和材料字段；不接收登录凭据。公开作业只作为不可信 JSON 数据解析，不执行其中的文本、代码或链接。网络跳转也只允许固定作业站的查询和详情读取接口，拒绝账户、上传和状态修改接口。

接下来分阶段接入只读扫描、演习与正式作战。执行器需要独占模拟器、每个任务 ID 的最终结果、有限重试、预算、资源消耗许可和配置回滚。日常30分钟上限保持不变；活动开荒需独立的按需入口及用户指定预算，不能隐式延长日常时间。

参考：[MAA 集成协议](https://docs.maa.plus/zh-cn/protocol/integration.html)、[作业协议](https://docs.maa.plus/zh-cn/protocol/copilot-schema.html)、[PRTS Plus 前端](https://github.com/ZOOT-Plus/zoot-plus-frontend)、[公开检索参数](https://github.com/ZOOT-Plus/ZootPlusBackend/blob/dev/src/main/kotlin/plus/maa/backend/controller/request/copilot/CopilotQueriesRequest.kt)。外部接口会变化，完整协议和关卡匹配尚需验证。
