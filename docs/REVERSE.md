# 逆向 COROS 移动端加密

当 COROS App 更新导致移动端登录失败时，按此文档重新逆向加密方案。

## 背景

社区版获取睡眠数据需要调用移动端 API (`apicn.coros.com/coros/user/login`)，
该接口的 `account` 和 `pwd` 字段经过客户端加密。

当前已知的加密方案：

```
算法:   XOR + PKCS7 + AES-128-CBC
IV:     b"weloop3_2015_03#"      ← 可能改变
Key:    app_key (随机数字串)      ← 每次登录随机生成，取自登录 payload
```

加密流程 (`coros_api.py:_mobile_encrypt`):
```
plaintext → XOR with app_key bytes (cyclic) → PKCS7 pad → AES-128-CBC → Base64
```

## 工具准备

```bash
# 核心工具（Linux/WSL 下）
apt install apktool binutils  # apktool + strings/objdump

# 如果没有 APK，先下载
# 去 https://apkmirror.com 搜索 "COROS" 下载最新版
# 或者从手机提取: adb pull /data/app/~~xxx/com.coros.../base.apk
```

## 逆向步骤

### 1. 解包 APK

```bash
apktool d coros.apk -o coros_unpacked
```

### 2. 定位加密库

```bash
# 找到 native 库
find coros_unpacked -name "*.so" | grep -i encrypt
# 已知的加密库名: libencrypt-lib.so
# 如果改名了，搜关键字:
strings coros_unpacked/lib/**/*.so | grep -i "weloop\|encrypt\|AES\|CBC"
```

### 3. 提取字符串找 IV

```bash
# 在找到的 .so 中搜已知 IV 或疑似 IV
strings coros_unpacked/lib/arm64-v8a/libencrypt-lib.so | grep -E "^[a-zA-Z0-9_#]{10,20}$"

# 搜 AES/CBC/PKCS 相关符号
strings coros_unpacked/lib/arm64-v8a/libencrypt-lib.so | grep -i "aes\|cbc\|pkcs\|iv\|key"
```

IV 通常是一个 16 字节的字符串，特征是字母数字 + 特殊字符（如 `weloop3_2015_03#`）。

### 4. 确认算法

```bash
# 查看导入的函数，确认加密库
objdump -T coros_unpacked/lib/arm64-v8a/libencrypt-lib.so | grep -i "aes\|EVP\|CBC\|encrypt"

# 如果导入了 OpenSSL 的 EVP_EncryptInit / AES_cbc_encrypt，算法大概率没变
# 如果换成了别的库（BoringSSL、libsodium 等），可能需要更深入分析
```

### 5. 用 Ghidra/IDA 定位加密函数（如果需要）

如果 `strings` + `objdump` 找不到新 IV，需要反汇编：

1. 用 Ghidra 打开 `.so` 文件
2. 搜索字符串引用 "AES" "CBC" "weloop" 等
3. 找到加密函数，确认参数：
   - **IV**: 通常是函数开头附近的全局常量，16 字节
   - **Key 来源**: 是参数传入还是从别处读取
   - **padding**: 是否是 PKCS7

### 6. 抓包验证（终极手段）

如果静态分析搞不定，用 mitmproxy 抓包对比：

```bash
mitmdump -w coros_login.dump
# 手机配代理 → 打开 COROS App → 登录
mitmdump -r coros_login.dump --mode regular@8082 '~u login' --flow-detail 3
```

看请求体里的 `account` / `pwd` 字段：
- 如果还是 Base64 编码 → 加密方案可能只改了 IV
- 如果变成新格式（如 JWT、hex）→ 加密方案完全变了

对比抓包的 `pwd` 和 Python 生成的 `pwd`（用已知加密方案），逐字节比对，推断改了什么。

## 代码更新位置

只需要改 `coros_api.py` 里的两个地方：

### 位置 1: IV 常量（行 32）

```python
# 当前值
_MOBILE_AES_IV = b"weloop3_2015_03#"

# 如果有变化，替换为新值
_MOBILE_AES_IV = b"new_iv_from_apk"
```

### 位置 2: 加密函数（行 107-126）

```python
def _mobile_encrypt(plaintext: str, app_key: str) -> str:
    # 如果 COROS 换了算法（不只是换 IV），修改这个函数
```

如果算法完全变了（比如换成 RSA 或者加了 HMAC），直接贴新实现。

### 位置 3: 登录 payload（行 139-149）

```python
payload = {
    "account": _mobile_encrypt(email, app_key) + "\n",
    "accountType": 2,
    "appKey": app_key,
    "clientType": 1,
    ...
}
```

如果登录接口新增了必填字段（如 `deviceId`、`timestamp`），在这里加。

## 验证

修改完成后运行：

```bash
# 先清理旧 token
python cli.py logout

# 重新认证（会触发移动端登录）
python cli.py auth

# 测试睡眠数据
python get_sleep.py
```

如果返回睡眠数据 → 修复成功。

## 补丁级防御（可选）

可以考虑加一个降级开关：如果移动端登录失败，用 mitmproxy 预设的 token 文件兜底：

```python
# .env 里可选
COROS_MOBILE_TOKEN_FALLBACK=eyJ...
```

这样即使加密方案变了，手动抓一次 token 填进去就能继续用，等逆向搞定了再更新。
