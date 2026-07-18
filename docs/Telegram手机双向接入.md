# Telegram 手机双向接入

## 它能解决什么

飞书自定义机器人现在主要是单向推送。Telegram 机器人可以先做成手机双向：

- 你在 Telegram 手机上发问题。
- 本地电脑上的量化助手收到问题。
- 系统调用现有模型生成回答。
- 回答自动发回 Telegram。

前提是：本地电脑要开着，监听程序要运行。

## 第一步：创建机器人

1. 打开 Telegram。
2. 搜索 `BotFather`。
3. 给它发 `/newbot`。
4. 按提示输入机器人名字，比如 `股票AI量化助手`。
5. 再输入一个以 `bot` 结尾的用户名，比如 `stock_ai_helper_bot`。
6. BotFather 会给你一串 token。

token 就像机器人钥匙，不要发到公开群。

## 第二步：填写配置

复制这个文件：

```text
C:\Users\HUAWEI\Documents\股票AI交易助手\config\telegram_bot.example.json
```

保存为：

```text
C:\Users\HUAWEI\Documents\股票AI交易助手\config\telegram_bot.json
```

然后把 `bot_token` 填成 BotFather 给你的 token，并把 `enabled` 改成 `true`。

## 第三步：启动双向助手

最简单的方式：双击项目里的这个文件：

```text
C:\Users\HUAWEI\Documents\股票AI交易助手\start_telegram_assistant.bat
```

也可以在项目目录运行：

```text
python scripts\run_telegram_gateway.py
```

窗口保持打开。只要它开着，Telegram 上发问题就会自动回复。

## 第四步：先查自己的 chat_id

给机器人发：

```text
/id
```

机器人会回复当前 chat_id。

如果以后只允许你自己使用，就把这个数字填到 `allowed_chat_ids` 里。

## 提问模板

```text
问：我现在空仓，资金5万，想做短线，今天适合出手吗？
```

```text
问：鼎龙股份现在怎么样，能不能低吸？
```

```text
问：我持有002468，成本15.80，1000股，要不要减仓？
```

```text
问：半导体这几天走弱，是回调还是退潮？
```

## 当前短板

- 本地电脑关机或程序关闭时，机器人不会回复。
- 当前回复基于本地已有模型报告和数据，实时行情仍要看数据更新时间。
- 事件面、突发新闻、公告还没有完全自动结构化，遇到重大消息要人工核验。
- 机器人只做辅助分析，不自动交易，不替代最终决策。

## 更智能的回复

当前 Telegram 入口分两层：

1. 本地量化模型先整理行情、评分、板块、个股和风险依据。
2. 如果配置了大模型 API Key，再由大模型把依据整理成更自然的中文结论。

如果没有配置大模型 API Key，系统会自动退回本地规则总结，不会影响机器人收发消息。

需要开启时，在这个文件里填写 `llm.api_key`，并把 `llm.enabled` 改成 `true`：

```text
C:\Users\HUAWEI\Documents\股票AI交易助手\config\telegram_bot.json
```

也可以不把 Key 写进文件，而是在电脑环境变量里设置对应的环境变量，比如 `DEEPSEEK_API_KEY`。

## 国内模型配置示例

### DeepSeek

```json
"llm": {
  "enabled": true,
  "provider": "deepseek",
  "api_key_env": "DEEPSEEK_API_KEY",
  "api_key": "你的DeepSeek Key",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "max_tokens": 900,
  "temperature": 0.2
}
```

### 通义千问/百炼

```json
"llm": {
  "enabled": true,
  "provider": "qwen",
  "api_key_env": "DASHSCOPE_API_KEY",
  "api_key": "你的百炼 Key",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode",
  "model": "qwen-plus",
  "max_tokens": 900,
  "temperature": 0.2
}
```

### Kimi/月之暗面

```json
"llm": {
  "enabled": true,
  "provider": "kimi",
  "api_key_env": "MOONSHOT_API_KEY",
  "api_key": "你的 Kimi Key",
  "base_url": "https://api.moonshot.cn/v1",
  "model": "moonshot-v1-8k",
  "max_tokens": 900,
  "temperature": 0.2
}
```
