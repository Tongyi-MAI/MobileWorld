# v1.0 internal test


## 1) 配置docker后端
- data 下包含备份数据文件
    - media
    - pgdata
    - redis
    - mastodon.sql.gz (optional)
    - system.tat.gz (optioanl)

## 2) app安装
- 模拟器安装修改版.apk,已配置证书
- 存放在：/mock_apps/mastodon-debug-revised-251008.apk

## 3) 登录测试
1. 启动docker后端，打开mastodon软件，直接log in
2. 搜索服务器：https://10.0.2.2
3. 账号密码登陆
- 管理员：`owner@gmail.com / password`
- 示例用户：`demo@gmail.com / password`
- 测试用户：`test@gmail.com / password`
- 邀请连接：https://10.0.2.2/invite/Bvs3y58t (未开通邮箱发送)
- 测试用户注册以及邀请链接注册参看sripts/seed.sh & register_custom.sh
