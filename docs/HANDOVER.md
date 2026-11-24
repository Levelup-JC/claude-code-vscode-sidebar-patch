# 交接说明

Claude Code 的 VS Code 插件（包名 `anthropic.claude-code`）侧边栏有几项本地改动。官方没有界面源码，不能提功能 PR，只能改本机安装包。

## 改动需求

- 分组行和组内会话的颜色分开。分组用浅橙底和左侧橙竖线，分组名和箭头偏橙，会话保持原色。
- 分组可以拖拽排序，组内会话跟着分组走。
- 只拖普通分组。放在目标上半段插到前面，下半段插到后面。
- 会话存在分组的 `sessionIds` 里，重排分组数组即可，不用单独搬会话。
- Ungrouped 和 Archived 两个区域不能拖。

## 重打脚本

`reapply.py` 按压缩代码的结构修改当前启用的插件包：`webview/index.js`、`webview/index.css`，以及宿主的 `extension.js`。每次写入前会在同目录留下 `.bak-before-group-patch` 备份。

启用版本看 `~/.vscode/extensions/extensions.json`。更新插件时会删掉整个旧目录，所以补丁不能放在插件目录里，脚本放在仓库里，更新删不掉。

接手步骤：

1. 运行 `python3 reapply.py`。
2. 在命令面板执行 `Developer: Reload Window`。
3. 确认橙色分组和拖拽都在。

如果输出 `BLOCKED`，说明新包的结构变了。按报错改 `reapply.py` 里的匹配规则。不要用旧备份覆盖新包。

## 自动重打

`install-launchagent.sh` 会安装一个 LaunchAgent，在登录时以及 `extensions.json` 变化时运行脚本。日志在 `~/Library/Logs/claude-code-sidebar-patch.log`。

## 分组状态

- 分组里有正在运行或等待输入的会话：分组行用更深的橙，并缓慢闪动。
- 分组里有未读的已完成会话：橙更深、色条更粗，不闪。
- 其余情况保持浅橙。
- 外层分组会把子分组的状态算进去。
- Ungrouped 和 Archived 同样按里面的会话上色，但这两行仍然不能拖。

## 会话拖入分组

会话可以拖到分组标题上，也可以拖到分组内部的会话区域。拖到子分组内部区域只会落到该子分组，不会冒泡到外层分组。

## 会话时间

会话行右侧原来显示相对时间（`5m`、`2h`、`3d`），现在显示最后一条消息完成的绝对时间：同年显示 `MM-DD HH:mm`，跨年显示 `YYYY-MM-DD HH:mm`。

## 两级分组

- 分组可以放进另一个分组，只到两级。
- 把分组拖到另一个分组行的中间，松手就收进去，行上会出现橙框。也可以在分组上右键，选择「放入」或「移到顶层」。
- 拖到上沿或下沿仍是排序。
- 已经装着子分组的组，不能再被收进别的组。
- 删除外层分组时，子分组回到顶层，会话仍留在子分组里。
- 上下级关系存在分组对象的 `parentId` 上。宿主另存一份副本（globalState 的 `sessionGroupParents:<目录>` 键），更新期间补丁未打上时，读取会从副本补回。

## 上下文

- 不自动压缩，空闲时也不压缩。
- 上下文用过一半后，输入框旁的圆点提示开新线程，点击发送 `/handoff`，不发送 `/compact`。
- `/handoff` 的提示词见 `optional/handoff.md`，是一个独立的 Claude Code 命令文件，需要单独放到 `~/.claude/commands/` 才生效。

## 模型按会话独立

- 切换模型只作用于当前会话，不写入全局的 `~/.claude/settings.json`。原版会写这个文件，其他正在运行的会话监听到变化就会跟着换模型。
- 每个会话的选择按会话 ID 记到 globalState 的 `sessionModels` 键，最多 500 条，超出时删最久没动过的。
- 会话重开时，查到记录就只给这个会话下发模型。
- 新会话还没拿到 ID 就选了模型，先暂存在通道上，拿到 ID 后再记录。
- 选回 default 会删掉这条记录，回到 `settings.json` 的默认模型。
- 新会话的默认模型仍取 `settings.json` 里的 `model`。
