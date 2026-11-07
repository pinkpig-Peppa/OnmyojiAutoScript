## 超鬼王（MetaDemon）

适配新版“祸至无日 / 祸主降临”活动界面。

### 页面流程

1. 主界面右侧活动栏点击 `超鬼王` 图标（`I_MD_RIGHT_ENTER`）；图标被收起时先点击 `I_MD_TOGGLE_BUTTON` 展开活动栏
2. 活动首页点击竖排 `祸主降临` 进入玩法主页（`I_MD_ENTER2`），主页识别规则为 `I_MD_MAIN`
3. 玩法主页循环：
   - 自己发现槽位为空（`I_MD_BOSS_EMPTY`）时，先尝试协助好友发现的鬼王（`C_MD_FRIEND_BOSS_AREA`，空态用 `I_MD_FRIEND_EMPTY` 与 `O_MD_FRIEND_EMPTY_TEXT` 兜底）
   - 没有可协助的鬼王时点击 `召唤鬼王`（`I_MD_FIND_DEMON`），弹出 `裂变之眼召唤队列` 后点击 `立即召唤`（`I_MD_SUMMON_NOW`，标题 OCR `O_MD_SUMMON_TITLE` 兜底）
   - 槽位有鬼王时点击槽位（`C_MD_SELF_BOSS_SLOT`）进入详情页
4. 鬼王详情页识别 `I_MD_CHALLENGE`，OCR 鬼王名字（`O_MD_FULL_NAME`）与血量百分比（`O_MD_HP_PERCENT`），按策略选择预设队伍后挑战
5. 疲劳值（`O_MD_EXHAUSTION`）已满或超时后返回主界面

### 配置

- `md_use_strategy`：开启后按鬼王名字匹配预设队伍
- `md_low_hp_threshold`：鬼王血量百分比不大于该值时使用第二套预设队伍，默认 40
- `meta_crafting_card`：新版合成界面暂未适配，保留配置但不执行合成

### 资源维护

`tasks/MetaDemon/md/` 下的 `image.json`、`ocr.json`、`click.json` 是资源声明，修改后在仓库根目录执行：

```bash
python dev_tools/assets_extract.py
```

生成 `tasks/MetaDemon/assets.py`（该文件由工具生成，不要手改）。模板图片统一放在 `tasks/MetaDemon/md/`。

### 已知限制

- 合成（`合成`）界面未适配，`meta_crafting_card` 不生效
- `auto_tea`（喝茶恢复疲劳）仍固定为 False
- 好友发现的鬼王卡片布局可能随版本变化，点击依赖区域坐标并以详情页识别兜底
- 5/6 星鬼王不再通过星级图标判定，改用详情页鬼王名字与血量百分比策略