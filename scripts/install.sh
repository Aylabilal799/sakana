#!/bin/bash
set -e

echo "=== Agnes Video Pipeline Installer ==="
echo "For Debian Trixie with 8GB RAM CPU VPS"
echo ""

echo "[1/6] Updating system..."
apt update && apt upgrade -y

echo "[2/6] Installing system dependencies..."
apt install -y python3 python3-venv python3-dev python3-pip ffmpeg git curl wget nginx espeak-ng libespeak-ng1 sqlite3 ufw logrotate

echo "[3/6] Setting up Python virtual environment..."
cd /root/sakana
python3 -m venv venv
venv/bin/pip install --upgrade pip setuptools wheel

echo "[4/6] Installing Python dependencies..."
venv/bin/pip install     "py-cord>=2.6.0" "fastapi>=0.100.0" "uvicorn>=0.23.0" "pydantic>=2.0.0"     "PyYAML>=6.0" "moviepy>=2.0.0" "requests>=2.28.0" "aiohttp>=3.8.0"     "aiofiles>=23.0.0" "python-dotenv>=1.0.0" "kokoro-onnx>=1.0.0"     "soundfile>=0.12.0" "srt>=3.5.0" "tenacity>=8.0.0" "websockets>=12.0"     "openai>=1.0.0" "pillow>=10.0.0" "numpy<2.0.0"

echo "[5/6] Downloading Kokoro TTS models..."
mkdir -p /root/sakana/models/kokoro
wget -q --show-progress -O /root/sakana/models/kokoro/kokoro-v1.0.onnx     https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
wget -q --show-progress -O /root/sakana/models/kokoro/voices-v1.0.bin     https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

echo "[6/6] Configuring Nginx..."
tee /etc/nginx/sites-available/agnes-videos << 'NGINX'
server {
    listen 8080;
    server_name _;
    root /root/sakana/output;
    autoindex off;
    location ~* \.mp4$ {
        add_header Content-Type video/mp4;
        add_header Cache-Control "public, max-age=86400";
    }
}
NGINX

ln -sf /etc/nginx/sites-available/agnes-videos /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8080/tcp
ufw --force enable

# Swap
fallocate -l 4G /swapfile 2>/dev/null || true
chmod 600 /swapfile 2>/dev/null || true
mkswap /swapfile 2>/dev/null || true
swapon /swapfile 2>/dev/null || true
if ! grep -q swapfile /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Systemd service
cp /root/sakana/systemd/agnes-pipeline.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable agnes-pipeline

echo ""
echo "========================================"
echo "Installation complete!"
echo "========================================"
echo ""
echo "NEXT STEPS:"
echo "1. Edit /root/sakana/config/.env with your credentials"
echo "   cp /root/sakana/config/.env.example /root/sakana/config/.env"
echo "   nano /root/sakana/config/.env"
echo ""
echo "2. Start the bot:"
echo "   systemctl start agnes-pipeline"
echo ""
echo "3. Check logs:"
echo "   tail -f /root/sakana/logs/bot.log"
echo ""
