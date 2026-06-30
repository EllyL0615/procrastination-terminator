# 新项目起手(一次性 playbook)

把这份文件的内容作为第一句话发给 Claude,末尾补上你的想法。当前目录就是项目根,直接在这里起手;约定见 `.claude/CLAUDE.md`,按它来(uv + ruff + mypy + pytest、默认扁平布局)。

## 起手步骤

1. 先清掉继承来的 git 历史:`rm -rf .git`,再就地 `uv init`(当前目录即项目根,别带项目名,否则会在里头再嵌一层)。这会建好新的 git 仓库 + `.python-version` + 骨架。**默认面向脚本:扁平布局,别一上来就 src/ + 打包。** 要写库 / 发布才用 `uv init --package`(src/ 布局),并补 `[build-system]` 打包配置(mypy `strict` 见下面 pyproject 注释)。
2. 铺 `pyproject.toml`:把下面「pyproject 覆盖项」那段叠在 `uv init` 生成的内容之上。
3. 通用约定已在 `.claude/CLAUDE.md`(别动它);项目特有事实新建根目录 `./CLAUDE.md`,据 `.claude/CLAUDE.md` 里「项目级 CLAUDE.md 的写法」起骨架(只写项目特有事实 + 覆盖项、≤100 行)。`SPEC.md` 没模板,按「文档与计划」的分节起。README 直接编辑 `uv init` 生成的那份。填好项目名、占位 《…》 别留空,确认 `plans/` 在 `.gitignore` 里。
4. 跑 `uv add --dev ruff mypy pytest` 装好工具链。
5. 收尾:删掉这份 `init.md`(一次性脚手架,起完手就不需要了)。
6. 先别写实现代码。我有个还很模糊的想法,我们先在 SPEC.md 上一来一回把它聊清楚——你来追问、补全范围和待解决问号,我拍板;拿不准就停下来问。

## pyproject 覆盖项

叠在 `uv init` 生成的 `[project]` 骨架之上。开发工具单独装:`uv add --dev ruff mypy pytest`。

```toml
# ---- Ruff (lint + format; replaces black / flake8 / isort) ----
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
# A reasonable default set; trim if noisy, extend to be stricter. Ruff's built-in default works too.
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM", "RUF"]
ignore = ["E501"]  # line length is the formatter's job

# ---- mypy ----
[tool.mypy]
python_version = "3.12"
# strict = true  # turn on when the project gets serious / you write a package

# ---- pytest ----
[tool.pytest.ini_options]
testpaths = ["tests"]
```

## pre-commit(可选)

多人协作 / 项目趋于正式时再加。复制成根目录 `.pre-commit-config.yaml`,然后 `uvx pre-commit install`(更快的替代:`prek install`,读同一份配置);手动跑全量:`uvx pre-commit run --all-files`;定期刷版本:`uvx pre-commit autoupdate`(下面的 `rev` 是起点,会过期)。

```yaml
repos:
  # Basic hygiene
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml            # also validates pyproject.toml
      - id: check-added-large-files

  # Ruff: lint --fix first, then format (order matters — --fix edits code)
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.20                 # pin to the ruff version uv installed (`uv run ruff --version`) to avoid drift
    hooks:
      - id: ruff-check
        args: [--fix]             # also sorts imports (rule I)
      - id: ruff-format

  # mypy: run via the local uv env so it sees project deps; checks the whole project, not per-file
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: uv run mypy .
        language: system
        types: [python]
        pass_filenames: false

  # Optional: run tests before commit. Slows every commit; usually better in CI.
  # - repo: local
  #   hooks:
  #     - id: pytest
  #       name: pytest
  #       entry: uv run pytest
  #       language: system
  #       types: [python]
  #       pass_filenames: false
```

---

我的想法:
.\docs\SPEC.md
