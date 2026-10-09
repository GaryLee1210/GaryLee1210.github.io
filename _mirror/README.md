# 镜像维护说明

本站采用**上游完整快照 + 独立个人配置 + 验证后发布**，不再调用 Fork 合并接口。

## 日常修改

- 账号、头像、网址、分析统计开关等：修改 [config.json](config.json)。它在构建时覆盖上游配置；根目录 `_config.yml` 保留原样。
- 关闭上游布尔开关使用 `false`，不要使用 `null`：Jekyll 合并配置时可能保留 `null` 对应的旧值。
- 自己新增或修改的页面、图片和模板：放在 `_mirror/overrides/` 下，路径与上游对应，例如 `_mirror/overrides/pages/my-project.md`。构建时覆盖同名文件，但不改动上游原始快照。
- 如直接修改并提交根目录中由上游管理的文件，下次同步会将这些修改保存成 overrides。直接删除的文件记录在 `_mirror/deleted.json`，只在构建时删除。如果根目录与同名 override 同时出现不同修改，任务会明确停止，要求保留想要的版本，避免猜测你的意图。
- 根目录 README、`.github/`、`.gitignore`、`CNAME` 与 `_mirror/` 由本站管理，上游更新不会覆盖。
- 想恢复某个文件跟随上游：删除对应 override，并从 `deleted.json` 移除其删除记录。

## 每日流程

1. 获取原仓库最新提交，网络失败时重试。
2. 生成完整源码快照，处理上游新增、修改、删除和目录迁移，不执行 Git merge。
3. 在 `_mirror/build/` 构建临时网站，叠加个人配置和 overrides。
4. 补充原作者署名、调整本站链接；检查核心页面、样式和署名。
5. 检查通过后上传构建产物，再以普通提交保存快照；不强推。并发修改会阻止推送，而不是覆盖新提交。
6. 发布已验证的产物，并核对线上 `mirror-status.json` 中的上游版本。

同步、手动发布和推送触发共用同一流程及并发组。每天都重新验证和发布，因此先前的临时部署错误会在后续运行再次尝试。每周记录一次成功检查，避免长期没有上游更新时触发仓库无活动暂停规则。

## 失败与恢复

这套设计消除了由上游与个人配置修改同一文件引发的**Git 合并冲突**，不承诺错误代码、服务故障、权限变动或资源超限也能成功。真实错误仍会在 Actions 中标红。

构建或验证失败时，不提交候选上游快照、不部署候选网站；现有 Pages 版本继续服务。发布服务本身失败时保留此前部署，后续运行再次尝试。工作流并不提供 GitHub 平台自身故障时的网站可用性保证。

在 [Sync upstream research notes](https://github.com/GaryLee1210/GaryLee1210.github.io/actions/workflows/sync-upstream.yml) 点击 **Run workflow** 可重试。成功提交及历史 GitHub Pages deployments 可用于回溯。改造前备份标签：`mirror-before-snapshot-2026-10-09`。

上游原始 README 保存在 [upstream-README.md](upstream-README.md)；准确同步版本及文件清单保存在 `state.json`。新布局中的站点账号来自本站配置，文章、原作者项目和经历仍属于 Tingde Liu，署名不会被改成维护者。
