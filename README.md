# 视频推流管理系统

基于 Flask + MediaMTX + FFmpeg 的多用户视频推流管理平台。

## 功能特点

- 🔐 **用户系统**：注册需邀请码，自定义账号密码
- 🔑 **邀请码管理**：管理员生成有时效的邀请码
- 📤 **视频上传**：每个用户独立目录
- 📡 **独立推流**：多用户可同时推流不同视频
- 📺 **HLS直播**：每个用户独立的 HLS 直播地址
- ⏰ **自动断流**：非管理员推流4小时自动停止
- 📏 **容量限制**：非管理员单文件2GB，总容量5GB
- 📋 **一键复制**：点击即可复制直播地址

## 系统要求

- Ubuntu 20.04+ / Debian 11+
- 100Mbps+ 上行带宽（推荐）

## 快速安装

```bash
# 下载并解压
tar -xzf video-stream-system.tar.gz
cd video-stream-system

# 运行安装脚本
chmod +x install.sh
sudo ./install.sh
```

根据提示输入：
- 服务器域名或IP
- 各服务端口（默认即可）
- 管理员账号和密码

## 服务管理

```bash
systemctl status mediamtx    # MediaMTX 状态
systemctl status videostream # Web服务状态
systemctl restart videostream # 重启Web服务
```

## 目录结构

```
/home/yuki/vd/
├── {用户ID1}/   ← 每个用户独立目录
├── {用户ID2}/
└── users.db     ← 数据库
```

## 访问地址

- 管理页面：`http://域名:13333`
- HLS直播：`http://域名:8888/vrcstream/{用户ID}/index.m3u8`
