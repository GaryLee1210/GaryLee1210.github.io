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
   - 使用本站保存的 Linux `dependencies/Gemfile.lock`，保留原站根目录锁文件原样。Bundler 以 frozen 模式安装，Jekyll、插件及传递依赖不会在每日同步时自动换版本。兼容现有锁文件的 Gemfile 编辑仍可同步；新增或不兼容的依赖需要先验证并更新本站锁文件。
   - 临时构建目录中的 Gemfile 将旧 `mingw` / `x64_mingw` / `mswin` 平台别名转换为 Bundler 支持的 `windows`，保留其他平台和原始源码，消除新版 Bundler 的平台弃用提示。
   - 使用 Sass 官方迁移器，将当前上游样式中的 `@import`、全局内置函数迁移到模块写法。转换只发生在临时构建目录，每次同步都会重新处理，因此不会冻结或覆盖上游的新主题。
   - 对比迁移前后编译得到的 CSS，必须逐字节一致且不再出现 Sass 弃用提示。随后使用已验证的 CSS 构建 Jekyll 页面，保留原 front matter 和 `/style.css` 地址；不再由浮动版本的 Ruby Sass 重新编译。
   - 样式工具固定为 Sass `1.106.1`、sass-migrator `2.6.1`，全部 npm 依赖通过 `styles/package-lock.json` 锁定。升级时一并更新版本与锁文件，运行 `node --test _mirror/styles/test-migrate.mjs`，再验证真实上游构建与页面。
4. 补充原作者署名、调整本站链接；检查核心页面、样式和署名。
5. 检查通过后上传构建产物，再以普通提交保存快照；不强推。并发修改会阻止推送，而不是覆盖新提交。
6. 发布已验证的产物，并核对线上 `mirror-status.json` 中的上游版本及本次运行/重试编号。即使上游没变，只修改构建工具，也必须看到本次产物才算发布验证通过。

同步、手动发布和推送触发共用同一流程及并发组。每天都重新验证和发布，因此先前的临时部署错误会在后续运行再次尝试。每周记录一次成功检查，避免长期没有上游更新时触发仓库无活动暂停规则。

## 构建工具的受控升级

当前运行时固定为 Python `3.13.17`、Node `24.21.0`（附带 npm `11.19.0`）、Ruby `3.4.11` 和 Bundler `4.0.23`，运行于 `ubuntu-24.04`。Ruby 3.2 已结束维护，因此不继续冻结旧版 Ruby。所有外部 Actions 使用完整提交 SHA，版本注释便于维护；Pages 上传动作内部的 upload-artifact 同样固定为提交 SHA。

Linux gem 锁文件以已成功发布的运行 `39752370296` 为基线，Jekyll 为 `4.4.1`。每次安装后核对 Ruby/npm/Python/Bundler 版本及锁文件，禁止自动重新解析依赖；测试也会阻止引入浮动 Actions 引用和范围运行时版本。

版本核对读取运行时的版本常量，并输出实际值用于排错；不依赖 `bundle --version` 的展示文案（Bundler 4 已移除旧的 `Bundler version` 前缀）。

升级工具时，应在同一改动中更新工作流的精确版本及 SHA、相应锁文件和版本断言，再运行 Python/Sass 测试及完整的 Linux 构建。不要通过删除锁文件、关闭 frozen、屏蔽错误来让升级通过。上游新增依赖时，在 Linux 和目标 Ruby 环境中从现有锁文件进行有针对性的 `bundle lock --update <gem>`，验证后将新锁文件保存回 `_mirror/dependencies/Gemfile.lock`。Windows 的根目录锁文件不替代该 Linux 锁文件。

固定版本用于可重复构建，不代替后续安全更新；定期维护时仍需审查受支持版本和补丁。GitHub 托管虚拟机的系统补丁、平台 API、权限和外部下载服务不在这些版本锁的控制范围内。官方 deploy-pages `v5.0.1` 内部仍会输出 Node 的 `punycode` 弃用提示；其动作源码使用 Node 24，当前能正常发布，保留该提示，不修改或隐藏官方动作日志。

## 失败与恢复

这套设计消除了由上游与个人配置修改同一文件引发的**Git 合并冲突**，不承诺错误代码、服务故障、权限变动或资源超限也能成功。真实错误仍会在 Actions 中标红。

构建或验证失败时，不提交候选上游快照、不部署候选网站；现有 Pages 版本继续服务。发布服务本身失败时保留此前部署，后续运行再次尝试。工作流并不提供 GitHub 平台自身故障时的网站可用性保证。

在 [Sync upstream research notes](https://github.com/GaryLee1210/GaryLee1210.github.io/actions/workflows/sync-upstream.yml) 点击 **Run workflow** 可重试。成功提交及历史 GitHub Pages deployments 可用于回溯。改造前备份标签：`mirror-before-snapshot-2026-10-09`。

上游原始 README 保存在 [upstream-README.md](upstream-README.md)；准确同步版本及文件清单保存在 `state.json`。新布局中的站点账号来自本站配置，文章、原作者项目和经历仍属于 Tingde Liu，署名不会被改成维护者。
