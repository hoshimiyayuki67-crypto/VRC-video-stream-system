# 视频推流管理系统

基于 Flask + MediaMTX + FFmpeg 的多用户视频推流管理平台，支持 Linux 服务器部署和 Windows 桌面运行。

---

## 功能特点

- 🔐 **用户系统**：注册需邀请码，自定义账号密码
- 🚀 **首次设置**：Windows 版首次启动自动引导创建管理员
- 🔑 **邀请码管理**：管理员生成有时效的邀请码
- 📤 **视频上传**：每个用户独立目录
- 📡 **独立推流**：多用户可同时推流不同视频
- 📺 **HLS 直播**：每个用户独立的 HLS 直播地址
- ⏰ **自动断流**：非管理员推流 4 小时自动停止
- 📏 **容量限制**：非管理员单文件 2GB，总容量 5GB
- 🔒 **安全**：PBKDF2 加盐密码哈希

---

## 项目结构

```
├── linux/                     ← Linux 部署（完整独立）
│   ├── install.sh             ← 一键安装脚本
│   ├── mediamtx.yml           ← 流媒体配置
│   └── app/                   ← Flask 后端
│       ├── app.py
│       └── templates/
│
├── windows/                   ← Windows 桌面版（完整独立）
│   ├── launcher.py            ← GUI 启动器
│   ├── build.py               ← PyInstaller 构建
│   ├── mediamtx.yml           ← 流媒体配置
│   └── app/                   ← Flask 后端
│       ├── app.py
│       └── templates/
│
└── .github/workflows/         ← CI 自动构建 Windows EXE
```

---

## 🐧 Linux 安装

### 系统要求
- Ubuntu 20.04+ / Debian 11+
- 100Mbps+ 上行带宽（推荐）

### 安装步骤

```bash
# 下载并解压
tar -xzf video-stream-system-v1.0.2-linux.tar.gz
cd video-stream-system/linux

# 运行安装脚本
chmod +x install.sh
sudo ./install.sh
```

根据提示输入：
- 服务器域名或 IP
- 各服务端口（默认即可）
- 管理员账号和密码

### 服务管理

```bash
systemctl status mediamtx     # MediaMTX 状态
systemctl status videostream  # Web 服务状态
systemctl restart videostream # 重启 Web 服务
```

### 目录结构

```
/opt/video_data/
├── {用户ID1}/   ← 每个用户独立目录
├── {用户ID2}/
└── users.db     ← 数据库
```

---

## 🪟 Windows 桌面版

下载 `VRCStream.exe`，双击运行。

- **首次启动**：自动进入设置向导，创建管理员账号
- **后续启动**：正常登录页，输入已创建的账号密码
- 数据存储在 EXE 同目录下的 `data/` 文件夹，便携化设计

---

## 访问地址

- 管理页面：`http://域名:13333`
- HLS 直播：`http://域名:8888/vrcstream/{用户ID}/index.m3u8`

---

## 技术栈

| 组件 | 用途 |
|------|------|
| Flask | Web 后端 |
| MediaMTX | 流媒体服务器 |
| FFmpeg | 视频推流 |
| SQLite | 用户数据库 |
| PyWebView | Windows GUI（仅 Windows 版） |
| PyInstaller | EXE 打包（仅 Windows 版） |
