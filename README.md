# DMShoot

多平台私信聚合桌面应用——抖音 / B站 双平台消息统一管理 + AI 自动回复。

![Python](https://img.shields.io/badge/Python-3.12-blue)
![PySide6](https://img.shields.io/badge/GUI-PySide6-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## 功能

- 🔌 **多平台私信聚合**：抖音、B站消息统一收发
- 🤖 **AI 自动回复**：DeepSeek API 驱动，支持多角色人格
- 📊 **性能监控**：API 延迟、消息速率、队列深度实时图表
- 🎨 **毛玻璃 UI**：深/浅双主题，毛玻璃弹窗
- ⚡ **Go 消息后端**（可选）：高性能消息处理

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

## 技术栈

- Python 3.12 + PySide6
- SQLite (WAL 模式)
- DeepSeek API (OpenAI 兼容)
- Playwright 浏览器自动化
- Go (可选消息后端)

## 项目结构

```
dmshoot/
├── ai/          # AI 后端 + 提示词
├── core/        # 消息总线、适配器管理、并发、限流
├── gui/         # PySide6 界面
├── plugins/     # 平台适配器（抖音/B站/小红书/快手）
├── storage/     # SQLite 数据库
└── utils/       # 工具（日志、签名、WebSocket）
```

## License

MIT
