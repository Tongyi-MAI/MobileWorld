#!/usr/bin/env bash
set -euo pipefail

# register_custom.sh
# 在文件内直接配置普通用户（无需命令行参数）
# 会在 Mastodon Docker 容器中创建普通用户账号（非管理员），并自动补确认、审批、设置密码。
#
# 用法：
#   ./register_custom.sh
#
# 可修改以下用户配置（按需增减）：



USERS=(
    # 格式：用户名:邮箱:密码
    # 注意：用户名只能包含小写字母、数字、下划线，且不能以数字开头
    "frank:frank@gmail.com:password"  # for report task
    "openUniversity:openUniversity@gmail.com:password"  # for agenda task
    "alex:alex@gmail.com:password"  # for create list task
    "emma:emma@gmail.com:password"  # for create list task
    "jack:jack@gmail.com:password"  # for create list task
    "rainbow123:RB123@gmail.com:password"  # for follow task
    "pupper:pupper@gmail.com:password"     # for favorite toots task
    "alice:alice@gmail.com:password"       # for save photos task
    "olivia:olivia@gmail.com:password"  # for revise contacts task
    
    "kitty:kitty@gmail.com:password"      # regular virtual user
    "gourmet:gourmet@gmail.com:password"  # regular virtual user
    "openCompany:openCompany@gmail.com:password"  # for notice sync task

    # "bob:bob@example.com:bob123"
)

# Docker Compose 环境配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="${COMPOSE_DIR:-"$(cd "$SCRIPT_DIR/.." && pwd)"}"
COMPOSE_FILE="${COMPOSE_FILE:-"$COMPOSE_DIR/docker-compose.yml"}"
PROJECT_NAME="${PROJECT_NAME:-mastodon-docker}"
SVC="${SVC:-web}"

# 容器内命令路径
BUNDLE=/opt/mastodon/bin/bundle
RAILS=/opt/mastodon/bin/rails
TOOTCTL=/opt/mastodon/bin/tootctl

# 检查 docker compose 可用性
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose -f "$COMPOSE_FILE" --project-name "$PROJECT_NAME")
elif docker-compose version >/dev/null 2>&1; then
  DC=(docker-compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME")
else
  echo "ERROR: docker compose / docker-compose 未安装" >&2
  exit 1
fi

# 构建 CSV 内容
CSV_LINES=""
for spec in "${USERS[@]}"; do
  IFS=':' read -r u e p <<<"$spec"
  u="${u//[[:space:]]/}"
  e="${e//[[:space:]]/}"
  if [[ -z "$u" || -z "$e" || -z "${p:-}" ]]; then
    echo "WARN: 跳过无效配置：$spec" >&2
    continue
  fi
  CSV_LINES+="${u},${e},${p}"$'\n'
done

if [[ -z "$CSV_LINES" ]]; then
  echo "没有有效用户配置，退出。" >&2
  exit 0
fi

echo "Registering ${#USERS[@]} user(s)..."

# 在容器内执行幂等注册
"${DC[@]}" exec -T "$SVC" sh -lc "
  set -e
  export PATH=\"/opt/ruby/bin:\$PATH\"
  cd /opt/mastodon
  $BUNDLE -v
  $RAILS  -v
  $TOOTCTL --version || true

  USERS_CSV=\$(cat <<'CSV_EOF'
${CSV_LINES}
CSV_EOF
)

  USERS_CSV=\"\$USERS_CSV\" $BUNDLE exec $RAILS runner - <<'RUBY'
csv = ENV.fetch('USERS_CSV', '').lines.map(&:strip).reject(&:empty?)
if csv.empty?
  puts 'No users to register.'
  exit
end

def log(msg) = STDOUT.puts(msg)

csv.each do |line|
  username, email, password = line.split(',', 3).map { |s| s&.strip }
  unless username && email && password && !username.empty? && !email.empty? && !password.empty?
    log \"Skip invalid row: #{line}\"
    next
  end

  # 幂等创建普通用户
  begin
    system(%{/opt/mastodon/bin/tootctl accounts create #{username} --email "#{email}" --confirmed}, exception: false)
  rescue => e
    log \"[WARN] tootctl create failed for #{username}: #{e}\"
  end

  user = User.joins(:account).find_by(accounts: { username: username })
  if user.nil?
    log \"[ERROR] user not found after create: #{username}\"
    next
  end

  # 如密码未设或不匹配则重设
  need_reset = false
  begin
    unless user.encrypted_password?
      need_reset = true
    else
      ok = false
      begin
        ok = user.valid_password?(password)
      rescue
        ok = false
      end
      need_reset = !ok
    end
  rescue
    need_reset = true
  end

  if need_reset
    user.password = password
    user.save!
    log \"set password: #{username}\"
  end

  # 补确认/审批
  if user.respond_to?(:confirm) && !user.confirmed?
    user.confirm
    log \"confirmed: #{username}\"
  end
  if user.respond_to?(:approve!)
    approved = user.respond_to?(:approved?) ? user.approved? : false
    unless approved
      user.approve!
      log \"approved: #{username}\"
    end
  end

  log \"ok: #{username} <#{email}>\"
end

log 'register_custom done.'
RUBY
"

echo "Done. 已处理 ${#USERS[@]} 个用户。"
