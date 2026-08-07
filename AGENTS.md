# 仓库指南

## 项目结构与模块组织

`app.py` 是 PyQt6 桌面应用入口。AI 编排代码位于 `Agent/CustomerAgent/`，其中 `custom/` 存放 Agent 框架实现，`tools/` 存放可调用工具。平台接入统一放在 `Channel/`；拼多多模块将连接与生命周期逻辑放在 `core/`，HTTP 接口封装放在 `utils/API/`。消息队列和处理器位于 `Message/`，`bridge/` 负责连接渠道事件与回复流程。通用服务、数据持久化、界面和工具分别位于 `core/`、`service/`、`database/`、`ui/` 和 `utils/`。测试放在 `tests/`，图标放在 `icon/`，Windows 打包文件放在 `scripts/`。

## 构建、测试与开发命令

- `uv sync`：根据 `uv.lock` 创建或更新 Python 3.11+ 环境。
- `uv run python app.py`：在本地启动桌面应用。
- `uv run python -m unittest discover -s tests -v`：运行完整回归测试。
- `uv run python -m unittest tests.test_regressions.ConfigRegressionTests`：运行单个测试类。
- `python scripts/build_win_exe.py --clean`：构建 Windows 目录包和 Inno Setup 安装程序；仅需 PyInstaller 产物时添加 `--skip-installer`。

## 编码风格与命名约定

Python 使用四空格缩进。模块、函数和变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。公共接口应添加类型标注，异步 I/O 明确使用 `async`/`await`。遵守现有包边界，不要把渠道专属逻辑放入共享模块。仓库未配置统一格式化或检查工具，因此应保持导入分组清晰、文档字符串简洁，并避免无关重构。

## 测试规范

测试使用标准库 `unittest`；异步场景使用 `IsolatedAsyncioTestCase`，外部依赖使用 `unittest.mock` 隔离。测试文件命名为 `test_*.py`，测试方法命名为 `test_<行为>`。身份隔离、配置持久化、数据库迁移、消息路由和 API 响应解析的变更必须补充回归测试。测试不得依赖真实平台账号、在线 LLM 密钥或个人数据。

## 提交与拉取请求规范

提交信息必须使用中文，并保持单一、明确的变更主题。建议沿用带范围的约定式格式，例如 `修复(登录)：清理浏览器配置锁文件`、`功能(打包)：支持自动读取版本标签`、`文档：更新构建说明`。不要在同一提交中混入无关格式化或重构。拉取请求应说明用户可见影响、列出验证命令并关联相关 Issue；UI 变更需附截图，Windows 专属验证或尚未覆盖的平台假设需明确说明。

## 安全与配置

禁止提交 `config.json`、API 密钥、Cookie、账号数据、`user_data/` 或 `temp/`。修改接口解析前，应使用真实响应或脱敏录制数据核对字段。调整配置、登录或数据库逻辑时，必须保留密钥保护和账号作用域隔离行为。

# Superpowers
- 存在 `.codex/COMMANDS.md` 时，遵循其中的指令
- 查看 `.codex/` 目录中的其他 Agent 配置和快捷方式
