#!/usr/bin/env bash
set -euo pipefail

#   seed.sh           # 创建 owner/demo/test 三个账号并各发一条帖子
#   seed.sh --invite  # 同时生成一个邀请链接（控制台打印）

MAKE_INVITE=0
if [[ "${1:-}" == "--invite" ]]; then
  MAKE_INVITE=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
PROJECT_NAME="mastodon-docker"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose -f "$COMPOSE_FILE" --project-name "$PROJECT_NAME")
elif docker-compose version >/dev/null 2>&1; then
  DC=(docker-compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME")
else
  echo "ERROR: docker compose / docker-compose 未安装" >&2
  exit 1
fi

# Compose服务名
SVC=web

# 容器内可执行文件路径
BUNDLE=/opt/mastodon/bin/bundle
RAILS=/opt/mastodon/bin/rails
TOOTCTL=/opt/mastodon/bin/tootctl

# account info
OWNER_USER="${OWNER_USER:-owner}"          # "admin" 为保留用户名
DEMO_USER="${DEMO_USER:-demo}"
TEST_USER="${TEST_USER:-test}"

OWNER_EMAIL="${OWNER_EMAIL:-owner@gmail.com}"
OWNER_PASS="${OWNER_PASS:-password}"

DEMO_EMAIL="${DEMO_EMAIL:-demo@gmail.com}"
DEMO_PASS="${DEMO_PASS:-password}"

TEST_EMAIL="${TEST_EMAIL:-test@gmail.com}"
TEST_PASS="${TEST_PASS:-password}"

WEB_DOMAIN="${WEB_DOMAIN:-10.0.2.2}"

echo "seeding users and sample statuses ..."
"${DC[@]}" exec -T "$SVC" sh -lc "
  set -e
  export PATH=\"/opt/ruby/bin:\$PATH\"
  cd /opt/mastodon

  # 版本自检
  $BUNDLE -v
  $RAILS  -v
  $TOOTCTL --version || true

  # 1) 用 tootctl 创建账户（若已存在会输出 taken, 保证幂等）
  $TOOTCTL accounts create $OWNER_USER --email \"$OWNER_EMAIL\" --confirmed --role Owner || true
  $TOOTCTL accounts create $DEMO_USER  --email \"$DEMO_EMAIL\"  --confirmed             || true
  $TOOTCTL accounts create $TEST_USER  --email \"$TEST_EMAIL\"  --confirmed             || true

  # 2) 设置密码、补确认/审批、发示例帖、(可选)生成邀请链接
  OWNER_USER=\"$OWNER_USER\" OWNER_PASS=\"$OWNER_PASS\" \
  DEMO_USER=\"$DEMO_USER\"   DEMO_PASS=\"$DEMO_PASS\" \
  TEST_USER=\"$TEST_USER\"   TEST_PASS=\"$TEST_PASS\" \
  WEB_DOMAIN=\"$WEB_DOMAIN\" MAKE_INVITE=\"$MAKE_INVITE\" \
  bash -lc 'export PATH=\"/opt/ruby/bin:\$PATH\"; $BUNDLE exec $RAILS runner - <<\"RUBY\"

owner = User.joins(:account).find_by(accounts: { username: ENV[\"OWNER_USER\"] })
demo  = User.joins(:account).find_by(accounts: { username: ENV[\"DEMO_USER\"]  })
test  = User.joins(:account).find_by(accounts: { username: ENV[\"TEST_USER\"]  })

# 设置密码（若已设置且正确则跳过）
def set_password(u, pwd, label)
  return unless u
  if !u.encrypted_password? || (pwd && !(u.valid_password?(pwd) rescue false))
    u.password = pwd
    u.save!
    puts \"set #{label} password\"
  end
end

set_password(owner, ENV[\"OWNER_PASS\"], \"owner\")
set_password(demo,  ENV[\"DEMO_PASS\"],  \"demo\")
set_password(test,  ENV[\"TEST_PASS\"],  \"test\")

# ======

# 补确认、审批，激活账户
[owner, demo, test].compact.each do |u|
  u.confirm  if u.respond_to?(:confirm)  && !u.confirmed?
  if u.respond_to?(:approve!)
    u.approve! unless (u.respond_to?(:approved?) && u.approved?)
  end
end

# ======

# 发示例帖子
def post!(user, text)
  return unless user
  # Status.create!(account: user.account, text: text)
  Status.find_or_create_by!(account: user.account, text: text)
  puts \"posted: #{text[0,30]}\"
end

post!(owner, \"Hello from Owner 👋\")
post!(demo,  \"Hello from Demo ✨\")
post!(test,  \"Hello from Test 🚀\")

# ======

# 可选：生成邀请链接
if ENV[\"MAKE_INVITE\"] == \"1\" && owner
  invite = Invite.create!(user: owner, max_uses: 5, expires_at: 7.days.from_now)
  puts \"Invite link: https://#{ENV.fetch(\"WEB_DOMAIN\", \"10.0.2.2\")}/invite/#{invite.code}\"
end

puts \"seed done.\"
RUBY'
"

echo "   Seed OK."
echo "   管理员（Owner）：$OWNER_EMAIL / $OWNER_PASS   （用户名：$OWNER_USER）"
echo "   演示用户：       $DEMO_EMAIL  / $DEMO_PASS    （用户名：$DEMO_USER）"
echo "   测试用户：       $TEST_EMAIL  / $TEST_PASS    （用户名：$TEST_USER）"
