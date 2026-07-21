#!/bin/bash
set -e

# ============================================================
# 视频推流管理系统 - 一键安装脚本
# 适用系统: Ubuntu 20.04+ / Debian 11+
# ============================================================

# 检查 root 权限
if [ "$(id -u)" -ne 0 ]; then
    echo -e "\033[0;31m❌ 请使用 root 权限运行此脚本: sudo ./install.sh\033[0m"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="/opt/video_app"
DATA_DIR="/opt/video_data"
MEDIAMTX_DIR="/opt/mediamtx"
MEDIAMTX_VERSION="1.19.2"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  视频推流管理系统 - 一键安装脚本${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ===================== 配置输入 =====================
echo -e "${YELLOW}请配置以下信息：${NC}"

read -p "服务器域名或IP [localhost]: " DOMAIN
DOMAIN=${DOMAIN:-localhost}

read -p "网页管理端口 [13333]: " WEB_PORT
WEB_PORT=${WEB_PORT:-13333}

read -p "HLS直播端口 [8888]: " HLS_PORT
HLS_PORT=${HLS_PORT:-8888}

read -p "RTMP推流端口 [1935]: " RTMP_PORT
RTMP_PORT=${RTMP_PORT:-1935}

read -p "管理员账号 [admin]: " ADMIN_UID
ADMIN_UID=${ADMIN_UID:-admin}

read -p "管理员密码: " -s ADMIN_PW
if [ -z "$ADMIN_PW" ]; then
    echo ""
    echo -e "${RED}密码不能为空！${NC}"
    exit 1
fi
echo ""

echo ""
echo -e "${GREEN}配置确认：${NC}"
echo "  域名: $DOMAIN"
echo "  网页端口: $WEB_PORT"
echo "  HLS端口: $HLS_PORT"
echo "  RTMP端口: $RTMP_PORT"
echo "  管理员账号: $ADMIN_UID"
echo ""
read -p "确认安装？(y/n): " CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo -e "${RED}安装已取消${NC}"
    exit 1
fi

# ===================== 步骤1: 系统依赖 =====================
echo ""
echo -e "${BLUE}[1/7] 安装系统依赖...${NC}"

apt-get update -y
apt-get install -y python3 python3-pip python3-venv ffmpeg curl wget screen \
    nginx ca-certificates gnupg lsb-release

echo -e "${GREEN}  ✅ 系统依赖安装完成${NC}"

# ===================== 步骤2: Python依赖 =====================
echo ""
echo -e "${BLUE}[2/7] 安装Python依赖...${NC}"

pip3 install flask flask-cors --break-system-packages 2>/dev/null || pip3 install flask flask-cors

echo -e "${GREEN}  ✅ Python依赖安装完成${NC}"

# ===================== 步骤3: 安装MediaMTX =====================
echo ""
echo -e "${BLUE}[3/7] 安装MediaMTX流媒体服务器...${NC}"

if [ -f "$MEDIAMTX_DIR/mediamtx" ]; then
    echo -e "${YELLOW}  MediaMTX已安装，跳过${NC}"
else
    mkdir -p $MEDIAMTX_DIR
    cd $MEDIAMTX_DIR
    
    # 检测系统架构
    ARCH=$(uname -m)
    case $ARCH in
        x86_64)  MTX_ARCH="amd64" ;;
        aarch64) MTX_ARCH="arm64v8" ;;
        armv7l)  MTX_ARCH="armv7" ;;
        *)       MTX_ARCH="amd64" ;;
    esac
    
    echo "  下载 MediaMTX v${MEDIAMTX_VERSION} (${MTX_ARCH})..."
    wget -q "https://gitcode.com/GitHub_Trending/me/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_linux_${MTX_ARCH}.tar.gz" -O mediamtx.tar.gz
    
    tar -xzf mediamtx.tar.gz
    rm mediamtx.tar.gz
    chmod +x mediamtx
    
    echo -e "${GREEN}  ✅ MediaMTX安装完成${NC}"
fi

# 配置MediaMTX
echo "  配置MediaMTX..."
cp "$SCRIPT_DIR/linux/mediamtx.yml" $MEDIAMTX_DIR/mediamtx.yml
# 更新端口配置
sed -i "s/hlsAddress: :8888/hlsAddress: :$HLS_PORT/" $MEDIAMTX_DIR/mediamtx.yml
sed -i "s/rtmpAddress: :1935/rtmpAddress: :$RTMP_PORT/" $MEDIAMTX_DIR/mediamtx.yml

echo -e "${GREEN}  ✅ MediaMTX配置完成${NC}"

# ===================== 步骤4: 创建数据目录 =====================
echo ""
echo -e "${BLUE}[4/7] 创建数据目录...${NC}"

mkdir -p $DATA_DIR
mkdir -p $APP_DIR/templates
echo -e "${GREEN}  ✅ 数据目录创建完成${NC}"

# ===================== 步骤5: 部署应用 =====================
echo ""
echo -e "${BLUE}[5/7] 部署应用...${NC}"

# 复制应用文件
cp "$SCRIPT_DIR/linux/app/app.py" $APP_DIR/
cp "$SCRIPT_DIR/linux/app/templates/index.html" $APP_DIR/templates/
cp "$SCRIPT_DIR/linux/app/templates/admin.html" $APP_DIR/templates/
cp "$SCRIPT_DIR/linux/app/templates/setup.html" $APP_DIR/templates/

# 修改端口 (如果非默认) — 精确匹配 app.run 中的 port=13333
if [ "$WEB_PORT" != "13333" ]; then
    sed -i "s/port=13333/port=$WEB_PORT/" $APP_DIR/app.py
fi

# 初始化数据库（创建管理员账号）
cd $APP_DIR
python3 -c "
import os, sqlite3, hashlib, secrets
os.makedirs('$DATA_DIR', exist_ok=True)
db = sqlite3.connect('$DATA_DIR/users.db')
db.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, salt TEXT, role TEXT DEFAULT \'user\', created_at TEXT DEFAULT (datetime(\'now\',\'localtime\')))')
db.execute('CREATE TABLE IF NOT EXISTS invite_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, created_by TEXT NOT NULL, expires_at TEXT NOT NULL, used_by TEXT, used_at TEXT)')
salt = secrets.token_hex(16)
pw_hash = hashlib.pbkdf2_hmac('sha256', '$ADMIN_PW'.encode(), salt.encode(), 100000).hex()
db.execute('INSERT OR IGNORE INTO users (uid, password_hash, salt, role) VALUES (?, ?, ?, \'admin\')', ('$ADMIN_UID', pw_hash, salt))
db.commit()
db.close()
print('管理员账号已创建: $ADMIN_UID')
"

echo -e "${GREEN}  ✅ 应用部署完成${NC}"

# ===================== 步骤6: 创建系统服务 =====================
echo ""
echo -e "${BLUE}[6/7] 创建系统服务（开机自启）...${NC}"

# MediaMTX 系统服务
cat > /etc/systemd/system/mediamtx.service << 'SERVICEEOF'
[Unit]
Description=MediaMTX Streaming Server
After=network.target

[Service]
Type=simple
ExecStart=/opt/mediamtx/mediamtx /opt/mediamtx/mediamtx.yml
Restart=always
RestartSec=5
User=root
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
SERVICEEOF

# 视频管理Web服务
cat > /etc/systemd/system/videostream.service << SERVICEEOF
[Unit]
Description=Video Stream Management Web App
After=network.target mediamtx.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/video_app/app.py
WorkingDirectory=/opt/video_app
Restart=always
RestartSec=5
User=root
Environment="DOMAIN=$DOMAIN"
Environment="HLS_PORT=$HLS_PORT"

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable mediamtx.service
systemctl enable videostream.service

echo -e "${GREEN}  ✅ 系统服务创建完成${NC}"

# ===================== 步骤7: 启动服务 =====================
echo ""
echo -e "${BLUE}[7/7] 启动服务...${NC}"

# 停止可能已运行的旧进程
screen -S videoapp -X quit 2>/dev/null || true

# 启动 MediaMTX
systemctl start mediamtx.service
echo -e "${GREEN}  ✅ MediaMTX 已启动${NC}"

# 启动 Web 服务
systemctl start videostream.service
echo -e "${GREEN}  ✅ Web服务 已启动${NC}"

# 创建管理员视频目录
mkdir -p "$DATA_DIR/$ADMIN_UID"

# ===================== 防火墙提示 =====================
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  🎉 安装完成！${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "请确保防火墙已开放以下端口："
echo -e "  ${YELLOW}TCP $WEB_PORT${NC}  - 网页管理界面"
echo -e "  ${YELLOW}TCP $HLS_PORT${NC}  - HLS直播流"
echo -e "  ${YELLOW}TCP $RTMP_PORT${NC} - RTMP推流"
echo -e "  ${YELLOW}TCP 8554${NC}       - RTSP推流（可选）"
echo ""
echo -e "如果使用 ufw，执行："
echo -e "  ${GREEN}ufw allow $WEB_PORT/tcp${NC}"
echo -e "  ${GREEN}ufw allow $HLS_PORT/tcp${NC}"
echo -e "  ${GREEN}ufw allow $RTMP_PORT/tcp${NC}"
echo ""
echo -e "${GREEN}📌 访问地址：${NC}"
echo -e "  🌐 管理页面: http://$DOMAIN:$WEB_PORT"
echo -e "  📺 HLS直播:  http://$DOMAIN:$HLS_PORT/vrcstream/{用户ID}/index.m3u8"
echo ""
echo -e "${GREEN}🔐 管理员账号：${NC}"
echo -e "  账号: $ADMIN_UID"
echo -e "  密码: $ADMIN_PW"
echo ""
echo -e "${GREEN}📂 视频目录：${NC}"
echo -e "  $DATA_DIR/{用户ID}/"
echo ""
echo -e "服务管理命令："
echo -e "  ${YELLOW}systemctl status mediamtx${NC}   - 查看MediaMTX状态"
echo -e "  ${YELLOW}systemctl status videostream${NC} - 查看Web服务状态"
echo -e "  ${YELLOW}systemctl restart videostream${NC} - 重启Web服务"
echo ""
echo -e "${BLUE}========================================${NC}"
