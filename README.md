# GaryLee1210 · AI 与机器人研究笔记学习镜像

[🌐 网站](https://garylee1210.github.io/) · [🧭 VLN 经典论文](https://garylee1210.github.io/VLN-Papers/) · [🔄 同步状态](https://github.com/GaryLee1210/GaryLee1210.github.io/actions/workflows/sync-upstream.yml)

完整镜像 [Tingde Liu 的研究笔记](https://tingdeliu.github.io/)，包含文章、配图、英文版和网站主题。原始文字、项目及经历属于原作者；本站由 GaryLee1210 维护供学习阅读。

## 自动同步

计划每天北京时间 **09:17** 获取上游完整快照。GitHub 可能延迟调度；流程在 GitHub 上运行，无需个人电脑开机。

采用**完整快照 + 独立个人配置 + 验证后发布**，不再进行分支合并：上游改名、移动目录或重写页面，不会与本站配置产生 Git 合并冲突。真实的构建错误、网络故障等仍会报告失败，候选构建失败时保留当前已发布的网站。

- 个人信息与站点参数：[配置文件](_mirror/config.json)
- 自定义页面、覆盖规则与恢复方式：[维护说明](_mirror/README.md)
- 上游原项目说明：[原始 README](_mirror/upstream-README.md)
- 线上已发布的上游版本：[mirror-status.json](https://garylee1210.github.io/mirror-status.json)

可以在 Actions 的 **Sync upstream research notes → Run workflow** 手动重试。每次正式更新前会运行自动化检查并验证核心页面、样式与署名；更新过程中不会强推覆盖你的提交。

## 来源与许可

本仓库 Fork 自 [TingdeLiu/tingdeliu.github.io](https://github.com/TingdeLiu/tingdeliu.github.io)，初始快照为 `dee0211b3acdeb531ac5e4b914e967b27b6e2f41`（2026-09-22）。后续快照版本记录在 `_mirror/state.json`，原有历史保留。

原始文字作者 **Tingde Liu**，依据 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 署名转载；代码沿用 [MIT](LICENSE)。第三方论文配图和引用材料的权利归其原作者或出版方，详见 [LICENSE-CONTENT](LICENSE-CONTENT)。
