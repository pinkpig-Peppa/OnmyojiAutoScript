# OAS 开发文档

> **仓库说明（2026-11）**：本文原为仓库维护者的内部开发笔记；上游 `runhey/OnmyojiAutoScript`、GUI 仓库 `runhey/OASX` 与文档站 `runhey.github.io/OnmyojiAutoScript-website` 均已被删除，故整理进本仓库作为开发参考。文中引用的 `OAS_pitfalls.md`、`OAS_project_rules.md`、`oas/module/*.md` 等为编写时的内部资料，**不在本仓库内**；与源码冲突时一律以本仓库源码为准。

> **本文合并自两份旧文档（2026-10-31，旧文件已删除，不再单独存在）**：
> - 原 `project_overview.md`（项目总览，提炼自仓库根 `README.md`）→ 第一部分
> - 原 `development_docs.md`（官方开发文档速查，提炼自官方文档站与 Alas Wiki）→ 第二、三部分
>
> **来源**：`https://runhey.github.io/OnmyojiAutoScript-website/docs/development/preamble` 及其子页（⚠️ 上游仓库与文档站已被删除，链接不可访问）；Alas Wiki `https://github.com/LmeSzinc/AzurLaneAutoScript/wiki`（OAS 三大基石继承自 Alas，官方页 3.2/3.3/3.4 直接指向 Alas Wiki，正文收录在文末「Alas Wiki 收录」一节）。
>
> **所有内容以本仓库源码为准**。官方文档迭代多、年久失修，根 README 里的「一条龙」「无缝」之类是宣传口径；引用任何「第 N 步打开 X」前先 `ls` / `grep -n` 落地（`OAS_pitfalls.md` 坑位 10、坑位 25）。

---

# 第一部分：项目概览

## 1.1 是什么

阴阳师手游自动化脚本。Windows / Python 3.10，GPL-3.0。一条龙托管：日常、每周、阴阳寮、御魂副本、肝帝项目、限时活动。

## 1.2 三端分立

| 组件 | 角色 |
|---|---|
| **OAS**（本仓库） | 后端执行引擎：设备控制、OCR/图像、任务调度、配置 |
| **OASX** | 全平台 GUI 前端（Flutter），只提供用户配置，**不承载运行逻辑** |
| **OAS-website** | 文档站（docusaurus，上游已删库） |

这条边界很重要：**OASX 里加字段不等于功能可用**，后端必须有对应读取与驱动逻辑（参见 `OAS_pitfalls.md` 坑位 23「字段与驱动必须成对」）。

## 1.3 继承自 Alas 的设计

OAS 基于碧蓝航线脚本 [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 开发，针对 StarRailCopilot 提到的问题做了这些调整：

- **前后端拆离**：OAS / OASX 分离，减少与具体游戏的耦合
- **新 GUI**：PySide6 + QML（原方案臃肿），见 `oas/module/gui/build.md`
- **新 OCR**：ppocr-onnx（onnxruntime + PaddleOCR），见 `module/ocr/`
- **新 Assets 管理**：图片/文字/点击统一由 json + `assets_extract.py` 生成 `assets.py`
- **配置 pydantic 化**：用户配置用 pydantic 模型管理，见 `oas/module/config/model.md`

## 1.4 功能面（用于判断某个任务属于哪一类）

- **日常**：悬赏封印、小猫咪、小杂签到、金币妖怪、年兽、花合战、地鬼、封魔、御魂整理
- **每周**：真蛇、秘闻竞速、神秘商店、搜刮商店、斗技、每周小杂事
- **阴阳寮**：结界上卡/蹭卡/突破、寮突破、狩猎战、集体任务、道馆
- **御魂副本**：八岐大蛇、业原火、日轮之城、永生之海、六道之门
- **肝帝**：探索、契灵、御灵、觉醒副本、石距、百鬼夜行
- **限时活动**：每期爬塔、超鬼王、对弈竞猜、花车巡游、智力答题

## 1.5 安装与文档入口

- 上游文档站已随仓库删除；本仓库内的开发参考资料见 `docs/development.md`，各任务说明见 `tasks/<Task>/README.md`
- 开发文档「年久失修」，**实现细节以源码为准**；本文第二部分是官方开发文档的提取速查

## 1.6 免责与环境约束

- 开源免费；任何渠道付费购买应退款
- 项目方明确不鼓励对外宣传（玩家群体对脚本排斥性强）

---

# 第二部分：开发范式

## 2.1 定位

官方开发文档讲的是框架和设计模式，不是函数字典（「不会把每个函数都复读一遍，要看函数细节去读源码」）。本部分把 10 个开发页（导言/PullRequest/用户选项/操控设备/过程元素/调试/日志/异常/装饰器/开发工具/游戏逻辑复用/编写任务示例）中与本项目强相关的信息浓缩成「开发规范速查」。

## 2.2 三大基石 + 死循环兜底

1. **User Option（用户选项）**：pydantic 配置驱动 GUI。层级 `任务(ConfigBase) → 选项组(BaseModel) → 选项(Field)`。详见 2.5。
2. **Manipulation Device（操控设备）**：封装模拟器/app 控制、截图、点击、滑动。脚本只调用高级接口（`self.click`/`self.appear_then_click`），不直接调 device API。
3. **Process Element（过程元素/assets）**：用 GUI 工具录 `image.json`/`ocr.json` → 跑 `assets_extract.py` → 生成 `assets.py`（`RuleImage`/`RuleOcr`/`RuleClick` 类）供代码引用。**不要手改 `assets.py`**，改要改 json 再重新 extract。
4. **死循环兜底（官方 6 节）**：
   - `GameStuckError`：无操作连续截图 ≥ 1 分钟（白名单场景延到 5 分钟）→ 最顶层捕获。
   - `GameTooManyClickError`：最后 15 次操作中同一项 ≥ 10 次，或两项各 ≥ 6 次（`module/device/device.py:click_record_check`） → 最顶层捕获。
   - 捕获后 OAS 把 log + 最近截图保存到独立目录，混淆路径/遮挡昵称后停止。
   - 这与 `module/device/device.py:29-33` 的 `stuck_record` 实现一致。

## 2.3 代码细节（官方 7 节）

- 注释模板用 PyCharm 默认的 docstring：`Description / :param / :return`
- **强制类型注解**，不用在注释里再写类型
- 一个函数注释占 1/3~1/2，函数 ≤ 1 屏，文件 ≤ 500 行
- 禁止在代码/标识符里用中文或拼音（注释可中文）

## 2.4 命名规范（官方 user-option 节）

任务名以游戏官方命名为准，不用中文/拼音：

| 用途 | 规则 | 示例 |
| --- | --- | --- |
| 任务目录 / 类名 / Enum | **大驼峰**，数字直拼 | `RaidMode`、`RaidMode9` |
| 变量名 / 字段 / 枚举值 | **下划线**，数字前加下划线 | `raid_mode`、`raid_mode_9` |

## 2.5 用户选项（User Option）

- 用 `pydantic.BaseModel + Field`，字段 `Field(default=..., description='...')`。
- `TimeDelta` 类型（`timedelta`）会被 OAS 序列化成 str，**继承 `ConfigBase` 即可**。
- 新增任务 7 步：
  1. `tasks/<Task>/config.py` 定义 `<Task>` 总配置类（继承 `ConfigBase`）
  2. 同路径建选项组类
  3. 每个选项组内定义选项（int/float/str/bool/Enum/TimeDelta/datetime/time）
  4. 在 `module/config/config_model.py` 的 `ConfigModel` 里挂 `<task>: <Task> = Field(default_factory=<Task>)`
  5. 在 `module/config/config_menu.py` 的 `ConfigMenu.__init__` 把任务加入导航组
  6. 在 `config_manual.py` 的 `SCHEDULER_PRIORITY` 里插入任务名（调度器按 `>` 排序，不暴露给 GUI）
  7. 翻译：OASX 侧 `./lib/config/translation/i18n_<lang>.dart`，或 OAS 侧 `./assets/i18n/zh-CN.json`（OASX 启动时拉一次，需启动两次才看得到变化）
- 访问选项：`self.config.model.<task>.<group>.<argument>`，或简写 `self.config.<task>.<group>.<argument>`（`Config.__getattr__` 透传到 `model`）。
- 隐藏选项：选项组类内加 `hide_fileds = dynamic_hide('arg_name')`，可隐藏多个。

## 2.6 操控设备（Manipulation Device）

官方页对模拟器/APP/截图/控制只列了 `screenshot_methods` / `click_methods` / `long_click_methods` 的键，**实现细节以本仓库 `module/device/` 源码为准**（已有对应 skill：`oas/module/device/device.md`、`screenshot.md`、`emulator.md`、`emulator_handlers.md`）。

- 截图源：`ADB` / `uiautomator2` / `DroidCast` / `scrcpy` / `window_background`
- 点击源：`ADB` / `uiautomator2` / `minitouch` / `window_message`
- 长按源：`ADB` / `uiautomator2` / `minitouch` / `window_message` / `scrcpy`
- 作者期望后续重写 device 为独立 lib（「目前 device 严重依赖 config」）。

## 2.7 过程元素（Process Element）

### RULE Tool（记录素材）

1. `./module/config/argument/setting.json` 的 `branch` 改 `dev` → 进入开发模式（⚠️ 该文件在当前版本已不存在，实际配置改为 `config/argument/*.yaml`，以源码为准）
2. 启动根目录 `gui.py`（老版）
3. 点最上方 `Screen Setting` 配置投屏：
   - `Image Source`：模拟器 / 本地图
   - `Frame Rate`：默认 2 帧
   - `ROI Model`：
     - `None`：两个框独立
     - `Same`：两框重叠且位置/大小一致（固定位置用这个）
     - `Include`：红框必须在绿框内（不确定位置时用）
   - 红框 = ROI_Front（默认），绿框 = ROI_Back（备选）
   - ⚠️ 官方强调「不要手贱乱拖边框」
4. 新建 `image.json` / `click.json` / `ocr.json`（约定路径 `./tasks/<Task>/res/`，但非强制）
5. 对 Image 规则：
   - 固定图片 → `ROI Model = Same`，一起拖两框
   - 非固定图片 → `ROI Model = Include` 或 `None`，绿框=可能区域、红框=当前目标
   - 每次记完点 `Save image`
   - `Threshold` 默认即可（代码里可 override）
6. 对 Ocr 规则：
   - `Mode` 选 5 种之一：`Single` / `Full` / `Digit` / `DigitCounter` / `Duration`
   - `Method = Default`
   - `Keyword`：`Single`/`Full` 时填要匹配的字符；其它模式不填
7. 对 List 规则（`RuleList`）：
   - 红框 = 每个元素的区域，绿框 = 整个列表
   - `Type = ocr`（绝大多数场景用这个；需要为每项截图的用 `image`）
   - 元素高度要和游戏界面里的实际高度一致（用于算滑动距离）
   - ocr 型要**游戏界面里只出现你定义的字符**（限制很强）
   - 方向选 `vertical`（大多数是竖直列表）
8. 每记几个点一次 `Save File`，最后再存

### Assets（json → 类）

```
./dev_tools/assets_extract.py 直接运行
```

- 生成 `./tasks/<Task>/assets.py`（自动 import 全部 `module/atom/*` 类）
- 类名固定为 `<TaskName>Assets`（例 `RealmRaidAssets`）
- 顶部注释 `# This file was automatically generated by ... # Don't modify it manually.`
- **每个 Rule 类型单独一份 json 文件**（官方鼓励多个 json，而非往一个里堆）

### API 速查（`module/atom/`）

**RuleImage**

- `match(image, threshold=None) -> bool`
- `coord() -> tuple`：红框随机坐标
- `coord_more() -> tuple`：绿框随机坐标

**RuleClick / RuleLongClick**

- `coord()` / `coord_more()` / `center()`
- `move(x, y)`：移动 roi_front
- LongClick 继承 Click，加 `duration`（ms）

**RuleSwipe**

- `coord() -> (x1, y1, x2, y2)`：红框起 + 绿框止
- `trace() -> list[tuple]`：滑动路径
- `Mode`：手滑（贝塞尔）/ 直线

**RuleOcr**

- `coord() -> tuple`：要求先跑过 ocr，返回匹配文字的 roi 坐标
- `ocr(image, keyword=None)` 按 `mode` 分派到 `Full/Single/Digit/DigitCounter/Duration.ocr_*`：
  - `Full` → `tuple`（匹配到 keyword 的合并区域，没匹配到 `(0,0,0,0)`）
  - `Single` → `str`
  - `Digit` → `int`（**是 int 不是 float**）
  - `DigitCounter` → `tuple`（x/y，无匹配 `(0,0,0)`）
  - `Duration` → `timedelta`（无匹配 `timedelta(0)`）

**RuleList**

- `swipe_pos(number=2, after=True)`：返回要滑动的两个点
- `image_appear(image, name)` / `ocr_appear(image, name)`：判断某项是否出现
- 底层仍受 RuleImage/RuleOcr 局限

**ImageGrid**

- 构造入参：`list[RuleImage]`
- `find_anyone()` → 命中的 RuleImage 对象

## 2.8 调试（官方 4 级入口）

| 层级 | 入口 | 用途 |
| -- | -- | -- |
| 顶层 | `gui.py` / `server.py` | 全量 GUI/服务（后者是新 OASX 配套） |
| 实例 | `script.py` 的 `__main__`：`Script('oas1').loop()` | 跑一个完整实例 |
| 任务 | `tasks/<Task>/script_task.py` 的 `__main__`：`Config('oas1') → Device → ScriptTask(c, d).run()` | 跑单个任务（最常用） |
| 素材 | `./dev_tools/assets_test.py`：`detect_image(path, target)` / `detect_ocr(path, target)` | 脱游戏、按截图验证素材 |

- `gui.py` 需 `pip install pyside6==6.4.3`（不在 `requirements.txt` 里）

## 2.9 日志 / 异常 / 装饰器

官方这三页全部**指回 Alas 的 Wiki**：

- Log → `https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/3.3.-Log`
- Exception → `https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/3.4.-Exception`
- Decorators → `https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/3.2.-Decorators`

本仓库的具体行为见 `OAS_pitfalls.md` 坑位 5/10（图像帧缓存、ui_click 死循环）与 `oas/module/base/retry.md`、`oas/module/base/decorator.md`。Alas Wiki 正文（3.1 Utils / 3.2 Decorators / 3.3 Log / 3.4 Exception / 4.1 Detection objects / 4.2 UI control / 4.3 OCR / 4.4 State loop）已收录在文末「Alas Wiki 收录」一节，按需查。

> **写日志前必读**：本节只管「怎么写日志」，**日志用什么语言**另有一条硬规范 —— 见 §3.6「日志语言规范」：**优先纯中文，其次中/英文对照，最后才纯英文**。技术标识（素材名/枚举/路径/异常类）不翻译。

## 2.10 开发工具（Dev Tools）

都在 `./dev_tools/` 下：

- `assets_extract.py`：跑一遍更新所有 `assets.py`
- `template_update.py`：更新 `./config/template.json`

## 2.11 游戏逻辑复用（Game Logic Reuse）

官方列了 6 类可继承组件。**本仓库实际文件位置与官方页略有出入（以源码为准）**：

| 类 | 官方路径 | 本仓库实际路径 | 关键方法 |
| -- | -- | -- | -- |
| `BaseTask` | `tasks/base_task.py` | 同 | `screenshot` / `appear(target, interval, threshold)` / `appear_then_click` / `wait_until_appear*` / `wait_until_disappear` / `swipe` / `click` / `ocr_appear` / `ocr_appear_click` / `list_find` / `set_next_run(target, server, success, task, finish)` |
| `GeneralBattle` | `tasks/Component/GeneralBattle/general_battle.py` | 同 | `run_general_battle()`（单人 5 式神+1 阴阳师）/ `run_general_battle_back()`（进挑战直返） |
| `GameUi` | `tasks/GameUi/game_ui.py` | 同 | `ui_get_current_page()`（改 `self.ui_current`）/ `ui_goto()`（自动算路由，先确认当前位置） |
| `GeneralBuff` | `tasks/Component/` | 同 | `open_buff` / `close_buff`（**只能在庭院用**）；`gold_50/100` `exp_50/100` `awake` `soul` |
| `GeneralRoom` | `tasks/Component/` | 同 | `create_room` / `ensure_private` / `create_ensure` / `exit_team` |
| `GeneralInvite` | `tasks/Component/` | 同 | 队长：`run_invite(config, is_first)` / `is_in_room` / `check_and_invite(default_invite)`；队员：`check_then_accept` / `wait_battle`（**成功=进战斗**，失败=退房间） |

`set_next_run(target, server, success, task, finish)` 参数语义：

- `target`：自定义下次时间
- `server`：True 时强制设为用户配置的每日时间
- `success`：用成功/失败间隔
- `task`：任务名（大驼峰）
- `finish`：以「完成时」还是「开始时」为基准算下次时间

## 2.12 编写任务（Task Example，以 RealmRaid 为例）

1. **User Option**：按 2.5 建 `config.py` + 选项组 + 选项，挂到 `ConfigModel` / GUI / 调度器。
2. **Process Element**：`./tasks/RealmRaid/res/` 放 `image.json` + `ocr.json`，跑 `assets_extract.py` 生成 `assets.py`。
3. **实现任务**：
   - 文件**必须叫** `script_task.py`
   - 类**必须叫** `ScriptTask`，入口**必须叫** `run()`
   - 类头：`class ScriptTask(GeneralBattle, GameUi, RealmRaidAssets):`（组合战斗/导航/本任务素材）
   - 典型循环：
     ```python
     while 1:
         self.screenshot()
         if self.appear_then_click(self.I_REALM_RAID, interval=1):
             continue
         if self.appear(self.I_BACK_RED, threshold=0.6):
             break
     ```
     `interval=1` 防止模拟器响应慢时误连点。
   - OCR 判票：
     ```python
     cu, res, total = self.O_NUMBER.ocr(self.device.image)
     if cu == 0 and cu + res == total:
         return False
     ```
   - 收尾：
     ```python
     self.set_next_run(task='RealmRaid')
     raise TaskEnd
     ```

## 2.13 Pull Request 流程（官方 8 步）

1. fork 主仓库
2. `git clone <your> -b dev`
3. 下载最新 release，把 `toolkit`/`deploy`/`console.bat` 拷到仓库根
4. `toolkit/python.exe -m pip install -r requirements.txt` + 单独装 `pyside6==6.4.3`
5. 开发 + 提交，commit message 固定格式：
   ```
   doc[(part)]: ...     # 文档
   feat[(module)]: ...  # 新功能
   perf[(module)]: ...  # 性能
   fix[(module)]: ...   # 修 bug
   ```
6. `git push -u origin`（首次 push 加 `--set-upstream`）
7. 在主仓库提 PR（**必须到 `dev` 分支，别合到 `master`**）
8. 有上游更新时：`git remote add upstream https://github.com/runhey/OnmyojiAutoScript.git` → `git fetch upstream` → `git rebase upstream/dev`（推荐）或 `git merge`

推荐 IDE：PyCharm / VSCode。

## 2.14 与本项目实践的差异点（以源码为准）

- 官方说「OAS 放弃除 1280x720 以外的分辨率支持」—— 本仓库代码同样硬性要求 1280x720（`module/device/screenshot.py:208-241`，非 720p 直接拒绝），`config/oas1.json` 的 `resolution` 不能绕过。
- 官方 `script.py` 的 `Script('oas1').loop()` —— 本仓库 `script.py` 实际由 `oas-backend.bat` 启动，多账号并发是 `oas1`/`oas2`/`oas3` 实例化。
- 官方 `screenshot_methods` 键 `aScreenCap` / `Hermit` / `MaaTouch` 在代码里注释掉了，实际只有 `ADB`/`ADB_nc`/`uiautomator2`/`DroidCast`/`DroidCast_raw`/`scrcpy`/`window_background`。
- 官方强调「device 严重依赖 config」，本仓库 `OAS_pitfalls.md` 坑位 6/8/9 记录了 `module/` 改动必须重启的实际表现。

## 2.15 速查卡（新任务落地 6 步）

1. `tasks/<Task>/config.py`：`<Task>(ConfigBase)` + 选项组 + 选项（pydantic）
2. 在 `module/config/config_model.py` 的 `ConfigModel` 挂 `<task>: <Task> = Field(default_factory=<Task>)`
3. 在 `module/config/config_menu.py` 的 `ConfigMenu.__init__` 加入 GUI 组
4. 在 `config_manual.py` 的 `SCHEDULER_PRIORITY` 里插任务名
5. `./tasks/<Task>/res/` 放 `image.json`/`ocr.json` → 跑 `./dev_tools/assets_extract.py`
6. 新建 `tasks/<Task>/script_task.py`：`class ScriptTask(...)` 继承 `GeneralBattle`/`GameUi`/`<Task>Assets`，入口 `def run()`，循环里 `self.screenshot()` + `appear_then_click(...)`

---

# 第三部分：Alas Wiki 收录

> 来源：`https://github.com/LmeSzinc/AzurLaneAutoScript/wiki`，收录 8 个 OAS 官方文档直接引用或强相关的章节。Alas 与 OAS 的 `Rule*` 体系同源，但类名/字段名不同（Alas 的 `Button` ≈ OAS 的 `RuleImage`，Alas 的 `Page` ≈ OAS 的 `GameUi`），本文保留 Alas 原样写法，OAS 侧对应关系在每条末尾标注。

## 3.1 状态循环（State Loop，Alas 4.4）⭐ 最重要

**原则**：低配/高配设备兼容靠的不是 `sleep()` 加时长，而是"状态循环"——把游戏每个 UI 视为一个"状态"，一次循环内遍历所有已知状态，命中即处理，命中退出态即跳出。禁止"点击-等待"模式，禁止在循环里 `sleep`。

### 标准写法

```python
def _x(self, skip_first_screenshot=True):
    while 1:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.screenshot()

        if self.appear(EXIT_CHECK):        # 退出：必须放在所有点击前面
            break
        if self.appear_then_click(A, interval=2):
            continue
        if self.handle_popup_confirm():
            continue
        if self.appear_then_click(B, interval=3):
            continue
```

关键要点（逐条对应 OAS 侧实现）：

| 要点 | 说明 | OAS 侧体现 |
| -- | -- | -- |
| `skip_first_screenshot` | 循环复用上一张截图，避免重复截图；**循环开始前必须显式 `self.screenshot()` 一次** | 直接继承，OAS `BaseTask.screenshot` 是封装层 |
| 退出条件在点击前 | 设备极慢时（截图耗时 > interval），仍能正确退出 | 同 |
| `interval` | 控制两次点击间的最短秒数（防连击），**只对点击生效，对 appear 退出条件无效**；跨循环复用要 `self.interval_clear(...)` 清计时器 | OAS `appear_then_click` 的 interval 参数 |
| 正面条件 | 永远用 `if self.appear(X)`，**不要写 `if not self.appear(X)`**（游戏动画/加载半开态容易误触） | 同 |
| 带操作语句不能当退出条件 | `appear_then_click`/`handle_*` 不能作为 `break` 条件（操作不在循环内、失败不重试） | 同；OAS 的 `ui_click` 嵌套用法见坑位 10 |
| 嵌套状态循环 | 原则上禁止；确需嵌套时子循环要负责退出自己的内部状态 | Alas 退役模块 `handle_retirement` 是典型嵌套正例 |
| `handle_*()` 命名约定 | 一组相关状态封装成函数，**返回 bool**：True 表示"我操作了游戏，外层循环需重新截图" | OAS `Component/*` 里通用方法同理 |

### 性能（Alas 量化数据，可参考）

- 99% 时间耗在等截图；`while` 内多扫几个 `appear` 的开销 < 1ms，可忽略。
- 截图耗时 50ms~100ms（特定组合 5ms~10ms），处理 2.5ms；OCR 100~180ms。
- Alas 默认限制截图发起间隔 300ms（`Screenshot._screenshot_interval`），防止 CPU 打满。

## 3.2 检测对象（Alas 4.1 Detection objects）

### Button（Alas） ≈ RuleImage（OAS）

- 字段：`area`（识别区域）/ `color`（平均色）/ `button`（点击区域）/ `file`（素材路径）
- **关键差异**：OAS 已拆成 `roi_front`（识别）+ `roi_back`（点击），`color` 字段 OAS 侧已不再用（用 `method="Template matching"` 或 `"Color matching"` 决定）
- 素材文件 `*.BUTTON.png` 可单独覆盖按钮点击区域（与识别区域分开）
- 匹配成功后自动记录 `_button_offset`（相对素材的像素偏移），**下一次点击自动应用该偏移** —— 游戏 UI 微调时不必重录素材
- `Template`（Alas）以 `TEMPLATE_` 开头，支持 GIF 多帧匹配；对应 OAS `RuleImage.method="Feature matching"` 的多帧特性
- `ButtonGrid`：二维网格生成一组 Button（`origin`/`delta`/`button_shape`/`grid_shape`）；对应 OAS `ImageGrid`

### 素材制作流程（Alas 原文，OAS 侧用 GUI 工具替代）

Alas 用 Photoshop 录制动作涂黑背景；OAS 直接用 `RULE Tool`（`./module/config/argument/setting.json` 的 `branch` 改 `dev`）的 `Save image` 完成等价操作（见 2.7），**OAS 侧无需手动 PS**。

## 3.3 UI 控制（Alas 4.2 UI control）

| Alas 类 | 作用 | OAS 侧对应 |
| -- | -- | -- |
| `Switch` | 游戏内开关（阵型/周回模式）：`add_status(name, button, sleep)` / `get(main)` / `set(name, main)` | `Component/quick_loadout.py` 等 |
| `Scroll` | 游戏内滚动条：`cal_position` / `at_top` / `at_bottom` / `set(0.5)` / `set_top` / `set_bottom` / `drag_page(0.5)` / `prev_page` / `next_page` | `RuleSwipe` + `RuleList.swipe_pos` |
| `NavBar` | 标签页：`get_active` / `get_total` / `set(left/right/upper/bottom=N)` | `GameUi` 部分 |
| `Page` | 界面识别（"出现 `check_button` 即视为在该页面"）+ 界面间 `link` 关系 | OAS `GameUi` 的 `Page` 类（`tasks/GameUi/page.py`），`ui_get_current_page` / `ui_goto` |

### 界面切换（Alas 全部带重试 + 自动寻路，OAS 继承）

- `ui_click(appear_button, click_button, check_button, additional)`：点击后确认到达目标页；`additional` 处理中途弹窗
- `ui_get_current_page()`：Alas 启动时调用；游戏未运行抛 `GameNotRunningError`，顶层捕获后启动游戏
- `ui_goto(dest)`：沿 `Page.link` 建的最短路径自动纠正
- `ui_ensure(dest)`：`ui_get_current_page` + `ui_goto`
- `ui_ensure_index(index, letter, prev, next, fast)`：数字翻页（队伍选择/猫箱数量）；`fast=False` 一次点一次识别（应对数字不连续场景）
- `ui_goto_main()` / `ui_back()` / `ui_additional()`：回主界面 / 点返回 / 处理切换中的弹窗

## 3.4 OCR（Alas 4.3）

OAS 已把 Alas 的 `Ocr`/`Digit`/`DigitCounter`/`Duration` 四类**整合为单一 `RuleOcr` + `mode` 参数**（见 `oas/module/atom/ocr.md`），语义对应：

| Alas 类 | 返回 | OAS `RuleOcr.mode` | 异常时返回 |
| -- | -- | -- | -- |
| `Ocr` | `str` | `Single` / `Full` | `""` / `(0,0,0,0)` |
| `Digit` | `int` | `Digit` | `0` |
| `DigitCounter` | `(cur, res, total)` 如 `14/15` | `DigitCounter` | `(0, 0, 0)` |
| `Duration` | `timedelta` 如 `08:00:00` | `Duration` | `timedelta(0)` |

Alas 侧 OCR 用的 `cnocr` + 三个预训练模型（`cnocr`/`azur_lane`/`jp`）——OAS 侧已换成独立 paddle-ocr 服务（port 22268，详见 `oas/module/ocr/rpc.md`）。

## 3.5 装饰器（Alas 3.2，`module/base/decorators.py`）

### `@Config.when(**kwargs)`

按 `config` 字段值分发同名函数，用于多服务器/多设备差异化逻辑：

```python
class Foo(ModuleBase):
    @Config.when(SERVER='en')
    def _commission_swipe(self, distance=190): ...

    @Config.when(DEVICE_CONTROL_METHOD='minitouch')
    def _commission_swipe(self, distance=300): ...

    @Config.when(None)          # 通配：以上都不匹配时执行
    def _commission_swipe(self, distance=300): ...
```

规则：

- 匹配 `None` 的分支**必须写在最后**（作为兜底）
- 可匹配 `config` 里任意字段，不限 `SERVER`
- 未命中任何一个 → `warning` 并运行最后定义的函数

OAS 侧 `oas/module/base/decorator.md` 有等价说明。

## 3.6 日志（Alas 3.3，`module/logger.py`）

日志格式：`%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s`，文件位置 `./log/{date}_{pyw_name}.txt`。

### 日志语言规范（2026-11-04 用户明确 · 写日志先看这条）

用户面向的日志文本按以下优先级取，**能中文就中文**：

| 优先级 | 形式 | 示例 | 适用 |
| -- | -- | -- | -- |
| 1 | **纯中文** | `logger.info('今日掉落未满（9/50），转去执行补票任务 Orochi')` | **默认档**，新写或改写的日志一律用这档 |
| 2 | **中/英文对照** | `logger.warning('战斗超时 / battle timeout')` | 该句有歧义、或这份日志要给不看中文的上游/协作者看时 |
| 3 | **纯英文** | `logger.info('Login success')` | 仅限上游原有代码且本次不打算改它 |

硬性边界：

- **技术标识不翻译**：素材名（`MD_MD_GET_BOSS`）、页面/枚举名（`page_meta_demon_boss`、`one_star`）、任务名（`Orochi`）、文件路径、异常类名、OCR 原始数值，一律保留原文。中文只包住「人话」部分。
- **`logger.hr()` 标题同样适用**：写 `logger.hr('召唤鬼王')`，不写 `logger.hr('Summon boss')`。
- **改日志文本 = 纯文本改动**：日志不参与 `appear` / 素材匹配，但改前确认没有下游 `grep` 依赖。已知的下游解析是 OASX 错误页的任务名（取 `[Task] <Name> (` 那行），与日志正文无关，正文中文化安全。
- **枚举/状态值转中文名**：日志写「一星」而不是 `one_star`。中文映射表放 `script_task.py` 顶部（如 `BOSS_TYPE_CN` + `boss_cn()`），**不放进 `config.py`**——配置类改动需要重启后端，日志改名不值得付这个代价。
- **不做全仓批量替换**：碰到哪个任务就把那个任务的日志改成中文，一次只动一个任务的文件。全仓大 diff 无法复核，且下次同步上游必然冲突。

落点范本：`tasks/MetaDemon/script_task.py`（2026-11-04 全量中文化，33 处 = 26 条 `info`/`warning`/`error` + 7 条 `hr` 标题）。

> ⚠️ 2026-11-08 重写的新版超鬼王流程（`tasks/MetaDemon/script_task.py`）暂用英文日志（便于与技术标识一致），尚未按本规范中文化，后续改动请按本文规范处理。

### `logger.hr(title, level)` 四级强调（**节制使用**，Alas 官方明确"不要把所有事都强调"）

| level | 用途 | 样式 |
| -- | -- | -- |
| 0 | 脚本启动时 | `+--- TITLE +---` |
| 1 | GUI 某功能开始 | `=== TITLE ===` |
| 2 | 功能某阶段开始 | `---- TITLE ----` |
| 3 | 某细分阶段开始 | `<<< TITLE >>>` |

### `logger.attr(name, text)` / `logger.attr_align(name, text, front, align)`

打印属性值（海图识别结果等密集打印用 `attr_align` 对齐）。

### 子目录运行

Alas 约定：在子目录里跑任何导入 `logger` 的脚本都会自动 `chdir` 回根目录，避免找不到资源。OAS 侧 `module/logger.py` 有无等价实现需要查源码。

## 3.7 异常（Alas 3.4，`module/exception.py`）

Alas 异常家族（OAS 继承其中 `GameStuckError` / `GameTooManyClickError` / `GameNotRunningError` 三条，其余为 Alas 独有）：

| 异常 | 抛出场景 | 捕获策略 |
| -- | -- | -- |
| `CampaignEnd` | BOSS 清/撤退/章节界面 | 结束关卡 |
| `MapDetectionError` | 海图识别参数/拟合失败 | 重新对准镜头再识别 |
| `MapWalkError` | 移动被敌舰挡或超步长 | 降 `FLEET_STEP=1` 重试 |
| `MapEnemyMoved` | 敌人会移动 | 重扫本关，上限 10 次，超出 `ScriptError('No combat executed.')` |
| `CampaignNameError` | 关卡名识别不到 | 重试上限 20 次，超出 `ScriptEnd` |
| `ScriptError` | 内部错误无法处理 | 若 `ENABLE_EXCEPTION=True` 直接撤退不抛 |
| `ScriptEnd` | 触发用户停止条件/识别失败 | 停止脚本 |
| `GameStuckError` | 60s/60 张截图无操作（战斗中 300s/300 张） | 仅 GUI 运行时重启游戏；再次触发不再捕获 |
| `GameTooManyClickError` | 最后 15 次点击中同一项 ≥ 12 次 | 仅登录时重启，最多 3 次，超出 `ScriptError('Login failed more than 3')` |
| `GameNotRunningError` | 未识别界面 + 游戏没跑 | GUI 运行时重启游戏 |
| `AscreencapError` | ascreencap 数据损坏 | 重新安装 ascreencap |

### "Exit without error"（Alas 静默退出的 15+ 种场景）

用户配置/使用方式错误，Alas 直接 `exit` 不抛异常，包括：分辨率非 1280x720 / 纯黑截图 / 找不到地图文件 / 无法回主界面 / UI 路由过长 / 未知共斗难度 / ADB 连不上 / 未退役任何船 / minicap 数据非 JPEG / 主副队同队 / 7~13 章只用了 1 队 / OCR 模型缺失 / 敌人模板缺失 / ascreencap 不支持该模拟器。

**OAS 侧差异**：OAS 已改成"最顶层捕获后把 log+截图打包到 `log/error/{script}_{timestamp}` 目录"（`OAS_project_rules.md`），不再是裸 `exit`；`GameStuckError` 白名单（战斗/启动中 5 分钟）与 Alas 的 `300s/300 张` 是同一设计。

## 3.8 工具函数（Alas 3.1，`module/base/utils.py`）

| 函数 | 作用 |
| -- | -- |
| `random_normal_distribution_int(a, b, n=3)` | [a, b) 内取 n 个随机数均值 → 模拟正态分布；Alas 绝大部分随机数来源 |
| `random_rectangle_point(area)` | 区域内 2D 正态分布随机点（点击用） |
| `random_rectangle_vector(vector, box, random_range, padding)` | 区域内按正态分布放置一个向量（滑动用） |
| `random_line_segments(p1, p2, n, random_range)` | 两点间插 n 段（滑动路径） |
| `area_offset/area_pad/point_in_area/area_in_area/area_cross_area` | 几何区域运算 |
| `node2location / location2node` | `E3` ↔ `(4, 2)`（Alas 海域坐标；OAS 已无此概念） |
| `crop(image, area)` | numpy 裁切，越界补黑（OAS `BaseCor.crop` 是它的简化：越界**返回空数组**，见 2026-10-22 崩溃修复） |
| `get_color(image, area)` | 区域平均色 |
| `color_similarity / color_similar / color_similar_1d / color_similarity_2d` | 颜色相似度（PS 魔棒容差算法；`_2d` 用 opencv，速度 3x，返回值中 255=完全相等） |
| `extract_letters(image, letter, threshold)` | 文字图转白底黑字（OCR 预处理；`Ocr` 类已封装） |
| `extract_white_letters` | 白字变体 |
| `red_overlay_transparency(color1, color2, red=247)` | 计算红色叠层不透明度（空袭/伏击/索敌动画识别） |
| `color_bar_percentage(image, area, prev_color, ...)` | 血条/进度条百分比（纯色/渐变/不连续均可，约 10ms，满进度返回 0.98~0.99） |

OAS 侧 `oas/module/base/utils.md` 已收录本仓库实际实现。
