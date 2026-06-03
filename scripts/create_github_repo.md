# 创建 GitHub private 仓库

仓库名：

```text
safety-vision-agent
```

建议在 GitHub 网页端创建 private 空仓库，然后在本地执行：

```bash
git remote add origin https://github.com/<your-name>/safety-vision-agent.git
git push -u origin main
```

如果使用 GitHub CLI：

```bash
gh repo create safety-vision-agent --private --source . --remote origin --push
```
