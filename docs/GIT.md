# 用 Git 管理项目

Git 保存代码的版本历史；GitHub 保存远程仓库，便于备份和协作。

在项目目录中完成修改、运行测试后：

```sh
git status
git diff
git add .
git commit -m "说明本次修改的内容"
git push origin main
```

`status` 查看改动，`diff` 比较内容，`add` 选择本次要保存的文件，`commit` 创建本地版本，`push` 将版本同步到 GitHub。推送需要使用仓库拥有者或具有写权限的账号完成 Git 身份认证；浏览器登录并不自动等同于命令行登录。

多人协作或较大修改时，先建立分支：

```sh
git switch -c feature/new-template
```

修改完成后将分支推送到 GitHub，再通过 Pull Request 审查和合并。使用 `git log --oneline` 查看历史版本。

数据库、上传图片、密钥、密码和本地配置已经通过 `.gitignore` 排除。提交前仍应检查改动，避免把真实业务数据写进源码或文档。Git 管理的是代码版本，运行数据需要单独备份。
