# 贡献指南

感谢你帮助改进 WeRSS。文档修正、问题复现、测试和代码提交都很有价值。

## 开始之前

请先搜索已有 Issue，避免重复。较大的功能或协议调整建议先开 Issue 说明使用场景、预期行为和安全影响。

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
pytest
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活环境。

## 提交要求

- 一个 PR 只解决一个清晰的问题；
- 保持现有分层：Web 路由、应用服务、协议与持久化各自负责；
- 新行为应增加或更新测试；
- 改变用户操作时同步更新 README 或技术文档；
- 不提交真实 Token、VID、Cookie、二维码或数据库；
- 不加入验证码自动化、代理轮换、高频重试或其他风控规避逻辑。

提交前运行：

```bash
ruff check .
pytest
```

## Pull Request 描述

请说明：

1. 改动解决了什么问题；
2. 关键实现与取舍；
3. 如何验证；
4. 是否影响数据格式、部署配置或平台请求行为。

参与项目即表示你同意按项目的 MIT 许可证贡献代码。
