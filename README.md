<div align="center">

# OnmyojiAutoScript

<br>

<div>
    <img alt="python" src="https://img.shields.io/badge/python-3.10-%233776AB?logo=python">
</div>
<div>
    <img alt="platform" src="https://img.shields.io/badge/platform-Windows-blueviolet">
</div>
<div>
    <img alt="license" src="https://img.shields.io/github/license/pinkpig-Peppa/OnmyojiAutoScript">
    <img alt="GitHub repo size" src="https://img.shields.io/github/repo-size/pinkpig-Peppa/OnmyojiAutoScript">
    <img alt="last commit" src="https://img.shields.io/github/last-commit/pinkpig-Peppa/OnmyojiAutoScript">
    <img alt="stars" src="https://img.shields.io/github/stars/pinkpig-Peppa/OnmyojiAutoScript?style=social">
</div>
<br>

阴阳师自动化脚本

一键托管

### 文档
- 开发文档：[docs/development.md](docs/development.md)
- 超鬼王（MetaDemon）任务说明：[tasks/MetaDemon/README.md](tasks/MetaDemon/README.md)

#### 本仓库: [https://github.com/pinkpig-Peppa/OnmyojiAutoScript](https://github.com/pinkpig-Peppa/OnmyojiAutoScript)

</div>

> **关于本仓库**：原上游 `runhey/OnmyojiAutoScript`、其 GUI 仓库 `runhey/OASX` 与文档站 `runhey.github.io/OnmyojiAutoScript-website` 均已被删除。本仓库是上游删除前 fork 出来的**独立维护分支**，继续承接修复与适配（例如 2026-11 新版超鬼王「祸至无日 / 祸主降临」界面适配，见 PR #8）。上游文档站已不可访问，其中的开发文档已整理进 [docs/development.md](docs/development.md)，其余以源码为准。

阴阳师，作为一个手游，已经进入了生命周期的晚期。从现在到关服的这段时间里，请减少花费在阴阳师上的时间，把一切都交给 OAS。

## 功能 Features

- **日常任务**: 悬赏封印、小猫咪、小杂签到、金币妖怪、年兽、花合战、地鬼、封魔、御魂整理
- **每周相关**: 真蛇、秘闻竞速、神秘商店、搜刮商店、斗技、每周小杂事
- **阴阳寮**: 结界上卡、结界蹭卡、结界突破、寮突破、狩猎战、集体任务、道馆
- **御魂副本**: 八岐大蛇、业原火、日轮之城、永生之海、六道之门
- **肝帝专属**: 探索、契灵、御灵、觉醒副本、石距、百鬼夜行
- **限时活动**: 每期爬塔、超鬼王、对弈竞猜、花车巡游、智力答题

### 显著特点
- **全部任务**: 你能想到的没有想到的都有，一条龙给你解放双手（该画饼画饼，该挖坑挖坑）
- **无缝衔接**: 时间管理大师，优异的任务调度系统，无缝寄养，无缝执行任务
- **装饰可选**: 全部初始皮肤是什么鬼，这里支持你喜欢的庭院、主题等等
- **百鬼夜行**: 利用 AI 智能撒豆子，模型包含所有式神

## 许可证 LICENSE

This project is licensed under the GNU General Public License v3.0.

## 声明 Announcement
本软件开源、免费，仅供学习交流使用。开发者团队拥有本项目的最终解释权。使用本软件产生的所有问题与本项目与开发者团队无关。
OAS is a free open source software, if you paid for OAS from any channel, please refund.
OAS 是一款免费开源软件，如果你在任何渠道付费购买了 OAS，请退款。

## 关于 Alas
OAS 基于碧蓝航线脚本 [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 开发，考虑到星穹铁道脚本 [StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot) 中所提及的问题，
OAS 在其基础上进行了如下优化：
- **调整设计架构**: 将前后端拆离出来更加灵活，方便后续的维护和扩展；优化代码架构使其减少同游戏耦合，更加通用。
- **搭建新的GUI**: 界面端拆分为独立项目 OASX（原项目已删库，本仓库只保留后端执行引擎与 `gui.py` 老版界面）。
- **新的OCR库**: 跟随 [LmeSzinc](https://github.com/LmeSzinc) 的步伐，[ppocr-onnx](https://github.com/triwinds/ppocr-onnx) 更加简易使用，精度更高速度更快。
- **新的Assets管理**: 构建了一个新的 Assets 管理系统，更加方便的管理游戏资源如图片，文字，点击等等（`tasks/<Task>/md/*.json` → `dev_tools/assets_extract.py` → `assets.py`）。
- **配置文件 [pydantic](https://github.com/pydantic/pydantic) 化**: pydantic 可以更加优雅的管理用户配置。

## 相关项目 Relative Repositories

- [Alas](https://github.com/LmeSzinc/AzurLaneAutoScript): 碧蓝航线的自动化脚本
- [SRC](https://github.com/LmeSzinc/StarRailCopilot): 星铁速溶茶，崩坏：星穹铁道脚本，基于下一代 Alas 框架。
- [ppocr-onnx](https://github.com/triwinds/ppocr-onnx): OCR 库，基于 onnxruntime 和 PaddleOCR
- [gurs](https://github.com/2833844911/gurs): 基于赛贝尔曲线模拟滑动轨迹，引入其轨迹模拟人手滑动
- ~~OASX~~、~~OAS-website~~：原 GUI 仓库与文档站，均已随上游一起删除

## 联系/加入我们 Contact/Join Us

相对于其他的游戏，阴阳师玩家总体而言对脚本这类工具具有极高的排斥性。树大招风，无论你是否喜欢 OAS，我们都希望你不在互联网上进行宣传，这保护 OAS，也保护开发者们。

为此保持较高的入群门槛：
#### QQ交流群: 1群465946275 2群1076565458
- 你的 QQ 等级必须大于 32 级，注册时间超过一年，低等级账号成分复杂，还请见谅。
- 你必须拥有一个 GitHub 账户来点一个 **Star**（这并不影响你入群后取消 Star），同样的要求注册时间过半年。
- 入群验证填入你的 GitHub `username`（不是 `name`），无需在意问题是什么，由 QQ 机器人审核。

#### QQ开发群: 207613181 (有意开发本项目请加此群，请不要胡乱加群)

- OAS 继承了 Alas 的设计思路，极大简便了开发，欢迎向本仓库提交 PR。
- 开发前请先读 [docs/development.md](docs/development.md)，实现细节以源码为准。

## 安装 Installation

1. 安装 Python 3.10（64 位）与 Windows 环境依赖：`pip install -r requirements.txt`；如需老版 GUI 额外安装 `pyside6==6.4.3`（不在 requirements 内）。
2. 将 `deploy/template` 复制为 `config/deploy.yaml`，按需填写 `Deploy.Git`（本仓库地址与分支）与 `Deploy.Python`。
3. 启动：后端 `python script.py`，GUI `python gui.py`；任务配置见 `config/<实例名>.json`（如 `config/oas1.json`）。
4. 模拟器分辨率必须为 **1280x720**（横屏），否则直接退出。
5. 上游文档站已删除；任务级说明见各任务目录下的 `README.md`（如 `tasks/MetaDemon/README.md`），开发约定见 [docs/development.md](docs/development.md)。

## 鸣谢 Acknowledgements

感谢所有参与到开发/测试中的朋友们。

[![Contributors](https://contributors-img.web.app/image?repo=pinkpig-Peppa/OnmyojiAutoScript)](https://github.com/pinkpig-Peppa/OnmyojiAutoScript/graphs/contributors)

原项目由 [runhey](https://github.com/runhey) 及其贡献者创建并维护，本仓库在其基础上继续维护。

<div align="center">

## ⚡ Visitor count

![](https://profile-counter.glitch.me/pinkpig-Peppa-OnmyojiAutoScript/count.svg)

</div>
