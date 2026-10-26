# bark-push

[Bark](https://bark.day.app/) 推送的 Python 封装，按 [请求参数](https://bark.day.app/#/params) 整理。只依赖标准库：`urllib` 发请求，内置纯 Python AES 实现加密推送。

- 支持 GET、POST 表单、POST JSON、`/push`、批量推送、删除通知
- 全部 23 个参数都有类型化的 Python 字段与校验
- 自动处理 URL 编码、UTF-8、超时、Bark 错误码
- 加密推送（AES-128/192/256-CBC + PKCS#7 + base64）无需第三方库

需要 Python 3.10+。

## 快速开始

```python
from bark_push import BarkClient, PushParams

client = BarkClient("your_device_key")  # 默认 https://api.day.app

client.send(
    PushParams(
        title="构建完成",
        body="bark-push 0.1.0",
        group="CI",
        level="timeSensitive",
    )
)
```

`send()` 默认使用 JSON（对特殊字符最稳妥），也可以用关键字直接构造参数：

```python
client.send(body="最简推送")
client.send(PushParams(title="表单", body="form 请求"), method="form")
client.send(PushParams(title="GET", body="你好"), method="get")
```

自建服务器：

```python
client = BarkClient("your_device_key", server="https://bark.example.com", timeout=5)
```

### 请求方式

| `method` | 请求 | 参数位置 |
|---|---|---|
| `"json"`（默认） | `POST /{key}` | JSON 请求体 |
| `"form"` | `POST /{key}` | `application/x-www-form-urlencoded` |
| `"get"` | `GET /{key}[/{title}[/{subtitle}]]/{body}` | 内容放路径，其余放查询串 |

GET 只有在 `body` 存在时才把 `title`/`subtitle` 放进路径；否则全部作为查询参数，避免产生有歧义的路径。所有路径段和参数值都会做 URL 编码。

### 批量推送

`device_keys` 只能用于 JSON，公共服务器一次最多 10 个设备，需要 bark-server v2.1.9+。传入字符串会报错，避免把 key 当成字符序列逐个发送。

```python
client.send_many(
    ["key1", "key2"],
    PushParams(title="通知", body="批量推送"),
)
```

### 把 key 放进请求体（`/push`）

```python
client.send(
    PushParams(device_key="key1", body="通过 /push 发送"),
    body_key=True,
)
```

`body_key=True` 时请求发往 `POST /push`，设备 key 必须来自 `params.device_key` 或 `params.device_keys`。普通 `/{key}` 请求不允许在参数里再带 `device_key`，避免路由歧义。

### 删除通知

```python
client.delete("notification-id")
# 等价于 PushParams(id="notification-id", delete=True)
```

删除通过静默推送下发，需要 `id`，并在系统设置里为 Bark 打开「后台 App 刷新」。

## 参数

字段名采用 snake_case，发送时自动转换为 Bark 的线上参数名。

| 字段 | 线上参数 | 类型 | 说明 |
|---|---|---|---|
| `title` | `title` | `str` | 标题，通知卡片第一行 |
| `subtitle` | `subtitle` | `str` | 副标题，标题下方的小字 |
| `body` | `body` | `str` | 正文 |
| `markdown` | `markdown` | `str` | Markdown 正文；传了会忽略 `body` |
| `device_key` | `device_key` | `str` | 设备 key；配合 `body_key=True` 使用 |
| `device_keys` | `device_keys` | `Sequence[str]` | 批量推送，仅 JSON |
| `group` | `group` | `str` | 消息分组 |
| `icon` | `icon` | `str` | 通知图标 URL（iOS 15+） |
| `image` | `image` | `str` | 通知大图 URL |
| `badge` | `badge` | `int / str` | 角标绝对值；`0` 清除角标 |
| `level` | `level` | `Level` / `str` | `active`、`timeSensitive`、`passive`、`critical` |
| `volume` | `volume` | `int / str` | 重要警告音量 0-10，仅 `critical` 生效 |
| `call` | `call` | `bool` / `"1"` | 铃声循环 30 秒 |
| `sound` | `sound` | `str` | 铃声名称，如 `minuet` |
| `copy` | `copy` | `str` | 复制推送时复制的内容 |
| `url` | `url` | `str` | 点击跳转 URL（Scheme / Universal Link） |
| `action` | `action` | `Action` / `str` | `alert` 弹操作框，`none` 只打开 App |
| `ciphertext` | `ciphertext` | `str` | 加密密文（base64） |
| `iv` | `iv` | `str` | 加密 IV（16 字节文本） |
| `is_archive` | `isArchive` | `bool` / `"0"` / `"1"` | 是否保存历史；`False` 会发送 `"0"` |
| `ttl` | `ttl` | `int / str` | 历史记录有效期（秒），必须 > 0 |
| `id` | `id` | `str` / `int` | 通知唯一标识；始终按字符串发送 |
| `delete` | `delete` | `bool` / `"1"` | 删除指定通知，必须配合 `id` |

说明：

- `call`、`is_archive`、`delete` 接受 `bool`、`0/1`、`"0"/"1"`。`call=False`、`delete=False` 等同于不传；`is_archive=False` 会明确发送 `"0"`（不保存），因为不传时由 App 内设置决定。
- `level` 只接受文档列出的四个值；`action` 允许其他字符串，服务端会按默认行为处理。
- `markdown` 与 `body` 可以同时存在，服务端会忽略 `body`。
- `title`、`subtitle`、`body` 传空串等同于不传；GET 因此不会生成 `/key/` 这种尾斜杠路由。
- `device_key` 与 `device_keys` 互斥。
- `id` 即使传数字也会转成字符串，符合 Bark「JSON 传数字不生效」的要求。

## 加密推送

在 App 首页的「推送加密」里设置 key。key 是 ASCII 文本，长度 16/24/32 字节分别对应 AES-128/192/256-CBC。

```python
client.send_encrypted(
    PushParams(title="加密标题", body="只有手机能解密", group="secret"),
    "1234567890123456",
)
```

默认生成随机的 16 字符十六进制 IV；也可以固定传入：

```python
client.send_encrypted(params, "1234567890123456", iv="abcdefghijklmnop")
```

加密内容包含 `title`、`subtitle`、`body`、`markdown`、`group`、`icon`、`image`、`badge`、`level`、`volume`、`call`、`sound`、`copy`、`url`、`action`。服务端控制字段（`isArchive`、`ttl`、`id`、`delete`、设备 key）保持明文，服务器才能执行保存、替换、删除等操作。批量加密推送不支持：每台设备需要独立密文。

服务端无法判断解密是否成功，密文错误时仍会返回 `200`；手机会显示 `Decryption Failed`。用错 key 或篡改密文时，可以用 `decrypt_payload` 在本地确认失败。

也可以只用加解密工具：

```python
from bark_push import decrypt_payload, encrypt_payload

encrypted = encrypt_payload({"body": "hello"}, "1234567890123456")
encrypted.ciphertext, encrypted.iv, encrypted.algorithm
decrypt_payload(encrypted.ciphertext, "1234567890123456", encrypted.iv)
```

## 响应与错误

```python
response = client.send(body="hello")
response.ok  # True
response.code  # 200
response.message  # "success"
response.data  # 服务端 data
response.payload  # 完整 JSON
```

异常层级：

```text
BarkError
├── BarkConnectionError   连接失败 / 超时
├── BarkHTTPError         非 Bark JSON 的 HTTP 错误
└── BarkAPIError          Bark 返回 code != 200
```

`BarkAPIError.code`、`.status`、`.response` 可用于排查；HTTP 错误对象也带 `.response`。

## 开发

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run coverage run -m unittest discover -s tests -v
uv run coverage report -m
```

Ruff 配置为 88 列、`target-version = "py310"`，启用 `E/F/I/UP/B/SIM/RUF`；`_aes.py` 的 FIPS-197 S-box 数据表单独忽略 `E501`。

实现只使用标准库；测试同样基于 `unittest`，并用本地 HTTP 服务器验证真实请求，用 NIST/FIPS-197 与 Bark 文档示例验证 AES。`coverage` 配置要求行覆盖率和分支覆盖率均为 100%，低于 100% 会直接失败。

测试覆盖了全部 23 个参数（含 `sound`、`image`、`icon`）、三种请求方式、`/push`、批量推送、删除、加密、错误映射，以及 AES 的密钥长度/块长度/PKCS#7 边界。
